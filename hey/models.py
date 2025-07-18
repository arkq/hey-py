from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatTools:
    NewsSearch: bool = False
    VideosSearch: bool = False
    LocalSearch: bool = False
    WeatherForecast: bool = False


@dataclass
class ChatMetadata:
    toolChoice: ChatTools = field(default_factory=ChatTools)


@dataclass
class ChatPayload:
    model: str
    messages: list[ChatMessage]
    metadata: ChatMetadata = field(default_factory=ChatMetadata)
    canUseTools: bool = False
