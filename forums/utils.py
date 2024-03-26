from fastapi import Request

from forums.db.topics import TopicRepository


def get_templates(req: Request):
    return req.app.state.tpl


def get_topic_repo(req: Request) -> TopicRepository:
    return TopicRepository(req.app.state.db)
