from forums.db.users import User
from fastapi import APIRouter, Depends, HTTPException, Form, Request

@app.get("/users/{{user.id}}")

