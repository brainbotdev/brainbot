from asyncio import TimeoutError
from os import getenv
from pathlib import Path
from random import sample
from time import time
from typing import List

from aiohttp import BasicAuth, ClientSession, ContentTypeError
from pyryver.objects import Chat, Creator, Notification, Ryver, Task
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
async def show_poll_results(
    chat: Chat, inputs: List[str], reactions: List[str], poll_id: str, bot_id: str
):
    console.log("Retrieving poll results")
    try:
        message = await retry_until_available(
            chat.get_message,
            poll_id,
            timeout=5.0,
            retry_delay=0.5,
        )
    except TimeoutError:
        console.log("[red]Failed when trying to retrieve poll message for results")
        return

    # Create association between options and their reactions
    poll_options = {}
    for i in range(0, len(reactions)):
        poll_options[reactions[i]] = inputs[i + 1]

    # Get poll number of reactions in count order
    poll_votes = []
    for emoji, users in message.get_reactions().items():
        # Remove bot reactions from count
        users.remove(bot_id)
        poll_votes.append([emoji, len(users)])
    poll_votes = sorted(poll_votes, reverse=True, key=lambda x: x[1])

    most_voted = poll_votes[0][1]

    # Send results
    msg_body = "\n## Poll results: {0}".format(inputs[0])

    for vote_reaction, vote_count in poll_votes:
        bold = "**" if vote_count == most_voted else ""
        poll_option = (
            " {0}".format(poll_options[vote_reaction])
            if vote_reaction in poll_options
            else ""
        )
        msg_body += "\n{3}{0} : :{1}:{2}{3}".format(
            vote_count, vote_reaction, poll_option, bold
        )
    await send_message(
        msg_body,
        chat,
    )


# Sorts notifications and executes suitable actions
async def handle_notification(ryver: Ryver, notification: Notification, bot_chat: Chat):
    # Check if it's a reminder notification
    if notification.get_predicate() == "reminder_for":
        # Check if it's a task reminder notification:
        if notification.get_object_entity_type() == "Entity.Tasks.Task":
            console.log("Task reminder received")
            task = await Task.get_by_id(ryver, obj_id=notification.get_object_id())
            # Check if it's a poll task
            if task.get_subject().startswith("BrainBotPoll#"):
                console.log(f"Poll {task.get_subject()} has ended")
                # Poll tasks are saved as "BrainBotPoll#<poll_id>" so there's the poll id
                poll_id = task.get_subject().replace("BrainBotPoll#", "")
                # Show poll results
                await show_poll_results(
                    chat=bot_chat,
                    inputs=(task.get_body().split(";;")[0]).split(";"),
                    reactions=(task.get_body().split(";;")[1]).split(";"),
                    poll_id=poll_id,
                    bot_id=(await ryver.get_info())["me"]["id"],
                )
                # Delete poll task
                console.log("Deleting poll reminder task")
                await task.delete()
                # Mark notification as read (Pyryver doesn't support removing notifications yet)
                console.log("Marking reminder notification as read")
                await notification.set_status(unread=False, new=False)

    else:
        # Discard irrelevant notifications
        await notification.set_status(unread=False, new=False)


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
