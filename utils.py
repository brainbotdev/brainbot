from os import getenv
from pathlib import Path
from random import sample
from time import time

from aiohttp import BasicAuth, ClientSession, ContentTypeError
from pyryver.objects import Chat, Creator, Ryver, Task
from pyryver.util import retry_until_available
from rich.console import Console

# Get a console to log to
console = Console()

# Get the bot's directory (this file's parent)
bot_dir = Path(__file__).parent.absolute()

# Creator to show the bot as... a bot
creator = Creator(
    name="BrainBot | Happy Halloween!",
    avatar="https://2.bp.blogspot.com/-uuIs6AxrKuQ/UvqYIdg8qTI/AAAAAAAAAMA/6UeTGIuxeWo/s1600/Fotolia_52196024_XS.jpg",
)

# Message sender utility to add a bot notice footer and use the bot's creator
async def send_message(message, chat, footer_end=""):
    footer = f"I am a bot made by the community. {footer_end}"
    footer = footer.strip().replace(" ", "^ ^")
    footer = f"^{footer}^"

    return await chat.send_message(
        f"{message}\n\n{footer}",
        creator=creator,
    )


# Task reminder creator
async def remind_task(ryver: Ryver, task: Task, minutes: int):
    """
    Apparently you can't either create reminders through pyryver or get the current session to send POST requests,
    so this method creates another session and sets the task reminder before closing it.
    """
    console.log("Opening another session to create a reminder")

    async with ClientSession(
        auth=BasicAuth(getenv("RYVER_USER"), getenv("RYVER_PASS")),
        raise_for_status=True,
    ) as session:
        url = ryver.get_api_url(
            obj_type="tasks",
            obj_id=task.get_id(),
            action="UserNotification.Reminder.Create()",
            format="json",
        )
        data = {"when": f"+{minutes} minutes"}
        console.log("Creating reminder")
        try:
            async with session.post(url, json=data) as resp:
                return (await resp.json())["d"]["id"]
        except ContentTypeError:
            pass
        console.log("Reminder created")
        await session.close()


# Retrieves poll results and shows it on chat as a reply to the original poll message
async def show_poll_results(chat: Chat, poll_id: str, bot_id: str):
    console.log("Retrieving poll results")
    message = await retry_until_available(
        chat.get_message,
        poll_id,
        timeout=5.0,
        retry_delay=0.5,
    )

    # Get poll number of reactions in count order
    poll_votes = []
    for emoji, users in message.get_reactions().items():
        # Remove bot reactions from count
        users.remove(bot_id)
        poll_votes.append([emoji, len(users)])
    poll_votes = sorted(poll_votes, reverse=True, key=lambda x: x[1])

    most_voted = poll_votes[0][1]

    # Reply on chat to show the results
    # Send poll text as reply to original message
    msg_body = ">{0}".format(message.get_body()).replace("\n", "\n>")
    msg_body += "\n## Poll results:"

    bold = ""
    for vote_reaction, vote_count in poll_votes:
        bold = "**" if vote_count == most_voted else ""
        msg_body += "\n{2}:{0}: : {1}{2}".format(vote_reaction, vote_count, bold)
    await send_message(
        msg_body,
        chat,
    )


# Cooldown utility
class Cooldown:
    def __init__(self, seconds: int):
        self.cooldown = seconds
        self.last_used = {}

    def run(self, username=None, bypass=False):
        if username not in self.last_used:
            self.last_used[username] = 0
        if time() - self.last_used[username] >= self.cooldown or bypass:
            self.last_used[username] = time()
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
