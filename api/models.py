from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str


class Source(BaseModel):
    section_path: str
    source_md_path: str
    pages: str
    links: list[dict]
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
