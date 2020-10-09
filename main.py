from asyncio import get_event_loop
from configparser import ConfigParser
from os import getenv, system
from string import punctuation
from sys import executable

from dotenv import load_dotenv
from git import Repo
from googletrans import Translator
from phonetic_alphabet import read as phonetics
from phonetic_alphabet.main import NonSupportedTextException
from py_expression_eval import Parser
from pyryver import Ryver
from pyryver.util import retry_until_available

from utils import Cooldown, TopicGenerator, bot_dir, console, send_message

__version__ = "1.0.0"

load_dotenv(
    dotenv_path=bot_dir / ".env"
)  # Added path to support older versions of python-dotenv

config = ConfigParser()
config.read("brainbot.ini")

tell_me_to_cooldown = Cooldown(config.getint("cooldowns", "tell_me_to", fallback=200))
topic_cooldown = Cooldown(config.getint("cooldowns", "topic", fallback=100))

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
                    console.log(f"Repeating {user.get_username()}")
                    if tell_me_to_cooldown.run(username=user.get_username()):
                        await send_message(
                            f"{msg_text}",
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
                    # Check length to ensure a value is there
                    if len(msg.text) <= 6:
                        await send_message(
                            "Please enter a word or phrase to be converted", bot_chat
                        )
                        return

                    try:
                        result = phonetics(msg.text.lower()[6:])
                    except:
                        await send_message(
                            "Your text contained one or more unsupported characters",
                            bot_chat,
                        )
                        return

                    await send_message(
                        f"++**Phonetic characters:**++\n{result}", bot_chat
                    )
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

            @session.on_connection_loss
            async def _on_connection_loss():
                await session.close()

            await session.run_forever()


# Run the async main function that was just defined
get_event_loop().run_until_complete(main())
