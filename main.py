from asyncio import get_event_loop
from os import getenv, system
from sys import executable

from dotenv import load_dotenv
from pyryver import Ryver
from pyryver.util import retry_until_available

from utils import Cooldown, TopicGenerator, bot_dir, console, send_message

__version__ = "0.2.2"

load_dotenv(
    dotenv_path=bot_dir / ".env"
)  # Added path to support older versions of python-dotenv

tell_me_to_cooldown = Cooldown(300)
topic_cooldown = Cooldown(120)

topic_engine = TopicGenerator()

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
            async def on_chat(msg):
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
                    if tell_me_to_cooldown.run():
                        await send_message(f"@{user.get_username()}: {to_do}", bot_chat)
                    else:
                        console.log("Cancelled due to cooldown")
                # Give the current version
                elif msg.text.lower().startswith("!version"):
                    console.log(f"Telling {user.get_username()} the current version")
                    await send_message(f"BrainBot v{__version__}", bot_chat)
                # Give an introduction of the bot
                elif msg.text.lower().startswith("!intro"):
                    console.log(f"Telling {user.get_username()} who I am")
                    await send_message(
                        "Hi! I'm BrainBot. I'm a fun, engagement-increasing bot made by the open-source community. Ask me for a list of commands if you'd like by saying `!commands`.",
                        bot_chat,
                    )
                # Give a list of commands
                elif msg.text.lower().startswith("!commands"):
                    console.log(f"Telling {user.get_username()} my commands")
                    await send_message(
                        "Here are my commands: !topic, !version, !commands, !intro, !restart (admin only), !topic bypass (admin only).",
                        bot_chat,
                    )
                 # Karma/Engagement system
                 karma = 0
                 elif msg.text.lower().startswith(f"!thanks{user.get_username()}"):
                    console.log(f"Adding 1 karma from {user.get_username()}")
                    karma+1
                    if karma = #pick a number
                        print("Goal reached :tada:")
                    
                    await send_message(
                        "",
                        bot_chat,
                
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
            async def on_connection_loss():
                await session.close()

            await session.run_forever()


# Run the async main function that was just defined
get_event_loop().run_until_complete(main())
