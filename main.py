from asyncio import get_event_loop
from configparser import ConfigParser
from datetime import datetime, timedelta
from os import getenv, system
from random import choice
from sys import executable
from urllib.parse import quote

from dotenv import load_dotenv
from git import Repo
from googletrans import Translator
from phonetic_alphabet import read as phonetics
from phonetic_alphabet.main import NonSupportedTextException
from py_expression_eval import Parser
from pyryver import Ryver, RyverWS
from pyryver.objects import Notification, TaskBoard
from pyryver.util import datetime_to_iso8601, retry_until_available
from pyryver.ws_data import WSEventData
from pytz import timezone

from utils import (
    Cooldown,
    TopicGenerator,
    bot_dir,
    console,
    handle_notification,
    remind_task,
    send_message,
)

__version__ = "1.3.0"

load_dotenv(
    dotenv_path=bot_dir / ".env"
)  # Added path to support older versions of python-dotenv

config = ConfigParser()
config.read("brainbot.ini")

tell_me_to_cooldown = Cooldown(config.getint("cooldowns", "tell_me_to", fallback=200))
topic_cooldown = Cooldown(config.getint("cooldowns", "topic", fallback=100))
repeat_cooldown = Cooldown(config.getint("cooldowns", "repeat", fallback=45))
phon_cooldown = Cooldown(config.getint("cooldowns", "phon", fallback=45))
poll_cooldown = Cooldown(config.getint("cooldowns", "poll", fallback=100))

# Load poll reactions
poll_reactions = config.get(
    "misc",
    "poll_reactions",
    fallback="zero;one;two;three;four;five;six;seven;eight;nine;keycap_ten",
).split(";")

math_parser = Parser()
topic_engine = TopicGenerator()
translator = Translator()


# Wrap in async function to use async context manager
async def main():
    # Log into Ryver with regular username/password
    async with Ryver(
        getenv("RYVER_ORG"), getenv("RYVER_USER"), getenv("RYVER_PASS")
    ) as ryver:
        console.log(
            f"Connected to {ryver.org} Ryver org as user {getenv('RYVER_USER')}"
        )

        # Save the bot chat to compare with all incoming messages
        await ryver.load_chats()
        console.log(f"Loaded {ryver.org} chats")

        bot_chat = ryver.get_chat(id=int(getenv("RYVER_CHAT")))

        # Get bot admins for restricted commands
        bot_admins = [
            ryver.get_user(username=user) for user in getenv("BOT_ADMIN").split(",")
        ]

        # Get bot user for task and timezone consults
        bot_user = ryver.get_user(id=(await ryver.get_info())["me"]["id"])

        # Get bot task board (used for setting timers)
        bot_task_board = await bot_user.get_task_board()
        if bot_task_board is None:
            console.log("Creating task board")
            await bot_user.create_task_board(
                board_type=TaskBoard.BOARD_TYPE_BOARD, categories=["BrainBot:Polls"]
            )
            bot_task_board = await bot_user.get_task_board()
        elif bot_task_board.get_board_type() == TaskBoard.BOARD_TYPE_LIST:
            console.log("Task list in use, BrainBot will not use categories for tasks")
        console.log(
            "Loaded user {0} task {1}".format(
                getenv("RYVER_USER"), bot_task_board.get_board_type()
            )
        )

        # Handle unread notifications from last session (used for checking reminders)
        async for notification in ryver.get_notifs(unread=True):
            await handle_notification(
                ryver=ryver, notification=notification, bot_chat=bot_chat
            )

        async with ryver.get_live_session() as session:
            console.log("In live session")

            @session.on_chat
            async def _on_chat(msg):
                # Stop if message wasn't sent to the bot chat
                if msg.to_jid != bot_chat.get_jid():
                    return

                # Get the user that sent the message
                user = ryver.get_user(jid=msg.from_jid)

                # Bypass the cooldown on the !topic command
                if msg.text.lower().startswith("!topic bypass"):
                    if user in bot_admins:
                        console.log(
                            f"{user.get_username()} used the !topic command [bold red](COOLDOWN BYPASS)"
                        )

                        topic_cooldown.run(bypass=True)

                        await send_message(
                            f"++**Conversation starter:**++\n{topic_engine.topic()}",
                            bot_chat,
                        )

                    else:
                        console.log(
                            f"[bold red]{user.get_username()} attempted to bypass the topic cooldown"
                        )
                
                # Get a conversation starter
                elif msg.text.lower().startswith("!topic"):
                    console.log(f"{user.get_username()} used the !topic command")

                    if topic_cooldown.run():
                        await send_message(
                            f"++**Conversation starter:**++\n{topic_engine.topic()}",
                            bot_chat,
                        )
                    else:
                        console.log("Cancelled due to cooldown")

                        # Get the invoking message
                        message = await retry_until_available(
                            bot_chat.get_message,
                            msg.message_id,
                            timeout=5.0,
                            retry_delay=0.5,
                        )

                        # React to show the command is on cooldown
                        await message.react("timer_clock")
                # "Someone tell me to" autoresponse
                elif msg.text.lower().startswith("someone tell me to "):
                    to_do = msg.text[19:]
                    console.log(f"Telling {user.get_username()} to {to_do}")
                    if tell_me_to_cooldown.run(username=user.get_username()):
                        await send_message(f"@{user.get_username()}: {to_do}", bot_chat)
                    else:
                        console.log("Cancelled due to cooldown")
                
                # Repeat after the user
                elif msg.text.lower().startswith("!repeat"):
                    msg_text = msg.text[8:]
                    updatedmsg_text = msg_text.replace("!","\!")
                    console.log(f"Repeating {user.get_username()}")
                    if repeat_cooldown.run(username=user.get_username()):
                        await send_message(
                            f"{updatedmsg_text}",
                            bot_chat,
                            footer_end=f"This command was run by {user.get_username()}.",
                        )
                    else:
                        console.log("Cancelled due to cooldown")
                # Give the current version
                elif msg.text.lower().startswith("!version"):
                    console.log(f"Telling {user.get_username()} the current version")
                    await send_message(f"BrainBot v{__version__}", bot_chat)
                # Translate a given word or phrase
                elif msg.text.lower().startswith("!translate"):
                    console.log(f"Translating for {user.get_username()}")
                    language = msg.text[11:13]
                    word = msg.text[14:]

                    translation = translator.translate(word, dest=language)

                    await send_message(
                        f"++**Translation result:**++\n{translation.text}",
                        bot_chat,
                        footer_end=f"This command was run by {user.get_username()}.",
                    )
                # Give an introduction of the bot
                elif msg.text.lower().startswith("!intro"):
                    console.log(f"Telling {user.get_username()} who I am")
                    await send_message(
                        "Hi! I'm BrainBot. I'm a fun, engagement-increasing bot made by the open-source community. Ask me for a list of commands if you'd like by saying `!commands`.",
                        bot_chat,
                    )
                # Evaluate a math expression
                elif msg.text.lower().startswith("!evaluate"):
                    inputs = [value.strip() for value in msg.text[10:].split(";")]
                    console.log(
                        f"Evaluating {'; '.join(inputs)} for {user.get_username()}"
                    )
                    try:
                        expression = math_parser.parse(inputs[0])
                    except:
                        console.log("[red]An error occurred during parsing")
                        await send_message(
                            "An error occurred while trying to parse your input.",
                            bot_chat,
                        )
                        return

                    variables = expression.variables()
                    if len(inputs) - 1 != len(variables):
                        console.log("[red]Incorrect number of variables provided")
                        await send_message(
                            f"You have not provided the correct number of variables. (Expected {len(variables)})",
                            bot_chat,
                        )
                        return

                    values = dict(
                        zip(variables, [float(value) for value in inputs[1:]])
                    )

                    try:
                        result = expression.evaluate(values)
                    except:
                        console.log("[red]An error occurred during evaluation")
                        await send_message(
                            "An error occurred while trying to evaluate your input.",
                            bot_chat,
                        )
                        return

                    await send_message(
                        f"++**Evaluation result:**++\n{result}", bot_chat
                    )
                # Give phonetic spellings
                elif msg.text.lower().startswith("!phon"):
                    console.log(f"Giving a phonetic spelling for {user.get_username()}")
                    # Check length to ensure a value is there
                    if phon_cooldown.run(username=user.get_username()):
                        if len(msg.text) <= 6:
                            await send_message(
                                "Please enter a word or phrase to be converted",
                                bot_chat,
                            )
                            return

                        try:
                            result = phonetics(msg.text.lower()[6:])
                        except NonSupportedTextException:
                            await send_message(
                                "Your text contained one or more unsupported characters",
                                bot_chat,
                            )
                            return

                        await send_message(
                            f"++**Phonetic characters:**++\n{result}", bot_chat
                        )
                    else:
                        console.log("Cancelled due to cooldown")
                # Random Emoticon
                elif msg.text.lower().startswith("!emoticon"):
                    emoticons = [
                        "`( ͡❛ ͜ʖ ͡❛)`",
                        "`O_o`",
                        "`（　0ゝ0 )`",
                        "`(╯°□°）╯︵ ┻━┻`",
                        "`:-)`",
                        "`<(o_o<)`",
                        "`(/^▽^)/`",
                        "`〠_〠`",
                        "`(￢‿￢ )`",
                        "`ᕕ( ᐛ )ᕗ`",
                    ]
                    console.log(f"Giving {user.get_username()} a random emoticon.")
                    await send_message(choice(emoticons), bot_chat)
                # Create Poll
                elif msg.text.lower().startswith("!poll"):
                    """
                    Command usage:  !poll [t=due_time;]<poll_title>;<option1>;<option2>...
                                    !poll [d=due_date;]<poll_title>;<option1>;<option2>...
                                    !poll [m=minutes;]<poll_title>;<option1>;<option2>...
                                    [] = Optional <> = Mandatory
                    Time should use the following format:   t=HH:MM
                                                            d=mm/dd/yyyy HH:MM
                                                            m=<minutes>
                        Time options d= ,t= and d= are not compatible.
                        In case of using more than one of them only the first one will be used, while the other
                        will be considered the rest of the arguments.
                        Bot timezone will be used.

                    Poll maximum option number depends of the amount of reactions in the config file
                    setting 'misc:poll_reactions'.

                    If due date/time is entered a task and a reminder will be created inside bot's personal
                    task board in order to make ryver take care of timers instead of the bot itself.
                    """
                    if poll_cooldown.run(username=user.get_username()):
                        # Get potential arguments
                        inputs = [value.strip() for value in msg.text[6:].split(";")]

                        # Remove any empty arguments
                        while "" in inputs:
                            inputs.remove("")

                        # Check if the command contains due date argument
                        due_date = None
                        if inputs[0].startswith("t="):
                            try:
                                # Parse ending time
                                due_date = inputs[0][2:]
                                due_date = datetime.strptime(due_date, "%H:%M")
                                # Get current time at bot timezone
                                current_date = datetime.now(
                                    timezone(bot_user.get_time_zone())
                                )

                                # If entered hour is earlier (or equal) than the current time, set date due for the next day
                                if current_date.time() >= due_date.time():
                                    due_date = datetime.combine(
                                        current_date.today() + timedelta(days=1),
                                        due_date.time(),
                                    )
                                else:
                                    due_date = datetime.combine(
                                        current_date.today(),
                                        due_date.time(),
                                    )

                                # Set date's timezone
                                due_date = due_date.astimezone(
                                    timezone(bot_user.get_time_zone())
                                )
                                inputs.pop(0)
                            except ValueError:
                                due_date = False

                        if inputs[0].startswith("d="):
                            try:
                                # Parse full ending date
                                due_date = inputs[0][2:]
                                due_date = datetime.strptime(due_date, "%m/%d/%Y %H:%M")
                                due_date = due_date.astimezone(
                                    timezone(bot_user.get_time_zone())
                                )
                                inputs.pop(0)
                            except ValueError:
                                due_date = False

                        if inputs[0].startswith("m="):
                            try:
                                due_date = int(inputs[0][2:])
                                # Get current time at bot timezone
                                current_date = datetime.now(
                                    timezone(bot_user.get_time_zone())
                                )
                                due_date = current_date.replace(
                                    microsecond=0
                                ) + timedelta(minutes=due_date, seconds=1)
                                inputs.pop(0)
                            except ValueError:
                                due_date = False

                        if due_date is None or due_date is not False:
                            current_date = datetime.now(
                                timezone(bot_user.get_time_zone())
                            )

                            # In case of valid due time, check if it's already in the past
                            if (
                                due_date is None
                                or int((due_date - current_date).total_seconds() / 60)
                                > 0
                            ):

                                # Check if the command contains a valid number of arguments
                                if len(inputs) < 3:
                                    await send_message(
                                        "Please enter a question and at least two options to create a poll",
                                        bot_chat,
                                    )
                                elif len(inputs) > (len(poll_reactions) + 1):
                                    await send_message(
                                        f"Your poll contained too many options, limit is {len(poll_reactions)} options",
                                        bot_chat,
                                    )
                                else:
                                    console.log(
                                        f'Creating poll "{inputs[0]}" for {user.get_username()}'
                                    )

                                    # Create formatted poll text
                                    poll_txt = "# {0}\n".format(inputs[0])
                                    for i in range(1, len(inputs)):
                                        poll_txt += ":{0}: {1}\n".format(
                                            poll_reactions[i - 1], inputs[i]
                                        )

                                    if due_date is not None:
                                        poll_txt += "\n\n**Poll will end on {0} at {1} ({2})**".format(
                                            due_date.date(),
                                            due_date.time(),
                                            due_date.tzname(),
                                        )
                                    poll_id = await send_message(
                                        poll_txt,
                                        bot_chat,
                                        f"This poll was created by {user.get_username()}",
                                    )

                                    # Get the poll message
                                    message = await retry_until_available(
                                        bot_chat.get_message,
                                        poll_id,
                                        timeout=5.0,
                                        retry_delay=0.5,
                                    )

                                    # Add reaction options
                                    for i in range(0, (len(inputs)) - 1):
                                        await message.react(poll_reactions[i])

                                    # Set ending timer using tasks
                                    if due_date is not None:
                                        task_body = "{0}".format(inputs[0])
                                        # Add options to task message for later parsing
                                        for i in inputs[1:]:
                                            task_body += ";{0}".format(i)
                                        # Add reactions used for later parsing
                                        task_body += ";"
                                        for i in poll_reactions[: (len(inputs) - 1)]:
                                            task_body += ";{0}".format(i)
                                        poll_task = await bot_task_board.create_task(
                                            f"BrainBotPoll#{poll_id}",
                                            task_body,
                                            due_date=datetime_to_iso8601(due_date),
                                        )
                                        # Create task reminder
                                        await remind_task(
                                            ryver,
                                            poll_task,
                                            int(
                                                (
                                                    due_date - current_date
                                                ).total_seconds()
                                                / 60
                                            ),
                                        )
                            else:
                                await send_message(
                                    "Ending time entered is already in the past or too short",
                                    bot_chat,
                                )
                        else:
                            await send_message(
                                "Ending time entered is not valid. You can any of these formats:\n `t=hh:mm;`\n `d=mm/dd/yyyy hh:mm;`\n`m=<minutes>;`\n**~Don't~ ~forget~ ~to~ ~use~ ~';'!~**",
                                bot_chat,
                            )
                    else:
                        console.log("Cancelled due to cooldown")

                        # Get the invoking message
                        message = await retry_until_available(
                            bot_chat.get_message,
                            msg.message_id,
                            timeout=5.0,
                            retry_delay=0.5,
                        )

                        # React to show the command is on cooldown
                        await message.react("timer_clock")
                # Give a list of commands
                elif msg.text.lower().startswith("!commands"):
                    console.log(f"Telling {user.get_username()} my commands")
                    await send_message(
                        "Check out [my wiki](https://github.com/brainbotdev/brainbot/wiki) to learn what commands I understand.",
                        bot_chat,
                    )
                # Pull the latest changes from GitHub
                elif msg.text.lower().startswith("!pull"):
                    if user in bot_admins:
                        try:
                            Repo(bot_dir).remotes.origin.pull()
                        except:
                            await send_message("Something went wrong.", bot_chat)
                            return
                        await send_message("Pulled successfully", bot_chat)
                    else:
                        console.log(
                            f"[bold red]{user.get_username()} attempted to restart the bot"
                        )
                # Render LaTeX
                elif msg.text.lower().startswith("!latex"):
                    await send_message(
                        f"![LaTeX](http://tex.z-dn.net/?f={quote(msg.text[7:])})",
                        bot_chat,
                    )
                # Restart the bot
                elif msg.text.lower().startswith("!restart"):
                    if user in bot_admins:
                        console.log("[bold red]Restarting bot")
                        system(f"{executable} {__file__}")
                        exit()
                    else:
                        console.log(
                            f"[bold red]{user.get_username()} attempted to restart the bot"
                        )
                # Shut down the bot
                elif msg.text.lower().startswith("!shutdown"):
                    if user in bot_admins:
                        console.log("[bold red]Shutting down bot")
                        exit()
                    else:
                        console.log(
                            f"[bold red]{user.get_username()} attempted to shut down the bot"
                        )

            @session.on_event(RyverWS.EVENT_ALL)
            async def _on_event(event: WSEventData):
                # Check if it's an incoming notification event
                # (Notification event type constant doesn't exist on PyRyver, so I hardcoded it)
                if event.event_type == "/api/notify":
                    notif = await Notification.get_by_id(
                        ryver, obj_id=event.event_data.get("id")
                    )
                    await handle_notification(
                        ryver=ryver, notification=notif, bot_chat=bot_chat
                    )

            @session.on_connection_loss
            async def _on_connection_loss():
                await session.close()

            await session.run_forever()


# Run the async main function that was just defined
get_event_loop().run_until_complete(main())
