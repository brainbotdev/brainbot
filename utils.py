from pathlib import Path
from random import sample
from time import time

from pyryver.objects import Creator
from pyryver.util import retry_until_available
from rich.console import Console

# Get a console to log to
console = Console()

# Get the bot's directory (this file's parent)
bot_dir = Path(__file__).parent.absolute()

# Creator to show the bot as... a bot
creator = Creator(
    name="BrainBot",
    avatar="https://2.bp.blogspot.com/-uuIs6AxrKuQ/UvqYIdg8qTI/AAAAAAAAAMA/6UeTGIuxeWo/s1600/Fotolia_52196024_XS.jpg",
)

# Message sender utility to add a bot notice footer and use the bot's creator
async def send_message(message, chat):
    await chat.send_message(
        f"{message}\n\n^I^ ^am^ ^a^ ^bot,^ ^bsoyka^ ^made^ ^me.^", creator=creator,
    )


# The main topic engine
class Topic:
    # Method to shuffle and reset the topics list
    def shuffle_topics(self):
        self.topics = sample(self.original_topics, len(self.original_topics))

    def __init__(self):
        # Load in the topics from topics.txt
        with open(bot_dir / "topics.txt") as file:
            self.original_topics = [line.strip() for line in file.readlines()]

        # Shuffle as defined previously
        self.shuffle_topics()

        # Set the time to 0 (the Epoch)
        self.last_used = 0

    async def topic(self, chat, msg, bypass=False):
        # Check if the last time the command was used was over 2 mins ago
        # or bypass is enabled
        if time() - self.last_used >= 120 or bypass:
            # If out of topics, re-shuffle
            if len(self.topics) == 0:
                self.shuffle_topics()

            # Get a random topic while also removing it from the queue
            random_topic = self.topics.pop()

            # Send the convo starter
            await send_message(f"++**Conversation starter:**++\n{random_topic}", chat)

            # Set the last used time to now
            self.last_used = time()
        else:
            console.log("Cancelled due to cooldown")

            # Get the invoking message
            message = await retry_until_available(
                chat.get_message, msg.message_id, timeout=5.0, retry_delay=0.5
            )

            # React to show the command is on cooldown
            await message.react("timer_clock")


class TellMeTo:
    def __init__(self):
        self.last_used = 0

    def can_use(self):
        if time() - self.last_used >= 300:
            self.last_used = time()
            return True
        else:
            return False
