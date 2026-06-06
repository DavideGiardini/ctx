from textual.message import Message
from textual.widgets import Input


class InputBar(Input):
    DEFAULT_CSS = """
    InputBar {
        dock: bottom;
    }
    """

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    async def action_submit(self) -> None:
        text = self.value
        self.value = ""
        self.post_message(self.Submitted(text))