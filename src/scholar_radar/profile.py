import json
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, field_validator

from .db import database, key
from .settings import dump, now


class Profile(BaseModel):
    city: str = "北京"
    target_start: str = "2027-06"
    graduation: str = "2029-06"
    internship_type: str = "研究型日常实习"
    goals: list[str]
    assets: list[dict]
    target_companies: list[str]
    excluded_companies: list[str] = []
    deferred_companies: list[str] = []
    excluded_topics: list[str] = []
    research_weights: dict[str,float] = {"opening":0.5,"interview_project":0.5}
    validation_weeks: list[int] = [1,2]
    active_limit: int = Field(1,ge=1,le=10)
    compute: dict
    current_actions: list[str] = []
    sources: list[dict] = []
    timezone: str = "Asia/Shanghai"
    daily_time: str = Field("07:30",pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weekly_day: int = Field(6,ge=0,le=6)
    monthly_day: int = Field(1,ge=1,le=28)
    daily_limit: int = Field(3,ge=0,le=5)
    weekly_directions: int = Field(3,ge=1,le=5)
    weekly_readings: int = Field(5,ge=1,le=10)
    fast_model: str = "deepseek-flash"
    strong_model: str = "deepseek-v4-pro"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls,value):
        ZoneInfo(value)
        return value


def save(db, obj):
    body = Profile.model_validate(obj).model_dump()
    pid = key("profile",body)
    db.execute("INSERT OR IGNORE INTO profiles VALUES(?,?,?)",(pid,now(),dump(body)))
    return pid


def get_profile(db, pid=None):
    row = (db.execute("SELECT * FROM profiles WHERE id=?",(pid,)).fetchone() if pid else
           db.execute("SELECT * FROM profiles ORDER BY rowid DESC LIMIT 1").fetchone())
    if not row:
        raise ValueError("请先导入个人画像")
    return {"id":row["id"],"recorded_at":row["recorded_at"],**json.loads(row["body"])}
