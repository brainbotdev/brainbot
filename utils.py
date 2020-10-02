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
    name="BrainBot | Happy Halloween!",
    avatar="https://i.imgur.com/LyRyO7V.png",
)

# Message sender utility to add a bot notice footer and use the bot's creator
async def send_message(message, chat):
    await chat.send_message(
        f"{message}\n\n^I^ ^am^ ^a^ ^bot^ ^made^ ^by^ ^the^ ^community.^",
        creator=creator,
    )


# Cooldown utility
class Cooldown:
    def __init__(self, seconds: int):
        self.cooldown = seconds
        self.last_used = 0

    def run(self, bypass=False):
        if time() - self.last_used >= self.cooldown or bypass:
            self.last_used = time()
            return True
        else:
            return False


# The main topic engine
class TopicGenerator:
    # Method to shuffle and reset the topics list
    def shuffle_topics(self):
        self.topics = sample(self.original_topics, len(self.original_topics))

    def __init__(self):
        # Load in the topics from topics.txt
        with open(bot_dir / "topics.txt") as file:
            self.original_topics = [line.strip() for line in file.readlines()]

        # Shuffle as defined previously
        self.shuffle_topics()

    def topic(self):
        # If out of topics, re-shuffle
        if len(self.topics) == 0:
            self.shuffle_topics()

        # Get a random topic while also removing it from the queue
        return self.topics.pop()
