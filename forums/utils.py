from fastapi import Request


def get_templates(req: Request):
    return req.app.state.tpl