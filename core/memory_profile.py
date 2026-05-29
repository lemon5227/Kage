"""
Memory Profile — 结构化用户档案存储

职责：
1. 存储用户的关键偏好和习惯 (JSON)
2. 支持 upsert（更新已有档案，而非追加）
3. 提供快速查询接口，无需向量搜索
"""

import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class UserProfile:
    """结构化用户档案"""
    # 基本信息
    name: str = ""
    city: str = ""
    occupation: str = ""
    timezone: str = ""

    # 偏好
    preferred_language: str = "zh-CN"
    preferred_tone: str = "natural"  # natural, formal, casual
    music_preference: str = ""
    food_preference: str = ""
    work_habits: list[str] = field(default_factory=list)

    # 习惯
    sleep_schedule: str = ""  # e.g. "23:00-07:00"
    work_schedule: str = ""
    exercise_habits: list[str] = field(default_factory=list)

    # 人际关系
    relationships: list[dict] = field(default_factory=list)
    # [{name, relationship, notes}]

    # 重要事件
    important_dates: list[dict] = field(default_factory=list)
    # [{date, event, reminder}]

    # 其他偏好
    app_preferences: dict = field(default_factory=dict)
    system_preferences: dict = field(default_factory=dict)

    # 元数据
    last_updated: str = ""
    version: int = 1


class MemoryProfile:
    """结构化用户档案管理"""

    def __init__(self, profile_path: str = "~/.kage/memory/profile.json"):
        self.profile_path = os.path.expanduser(profile_path)
        self.profile = self._load_or_create()

    def _load_or_create(self) -> UserProfile:
        """加载已有档案或创建新档案"""
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return UserProfile(**data)
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
        return UserProfile()

    def save(self) -> None:
        """保存档案到文件，同时记录版本历史"""
        os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)
        import datetime
        self.profile.last_updated = datetime.datetime.now().isoformat()
        self.profile.version += 1

        # Save version history before overwriting
        self._save_version_history()

        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.profile), f, ensure_ascii=False, indent=2)

    def _save_version_history(self) -> None:
        """Save current profile to version history before updating."""
        history_dir = os.path.join(os.path.dirname(self.profile_path), "history")
        os.makedirs(history_dir, exist_ok=True)

        history_file = os.path.join(history_dir, f"v{self.profile.version}.json")
        if not os.path.exists(history_file):
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(asdict(self.profile), f, ensure_ascii=False, indent=2)

    def get_version_history(self) -> list[dict]:
        """Get list of available profile versions."""
        history_dir = os.path.join(os.path.dirname(self.profile_path), "history")
        if not os.path.exists(history_dir):
            return []

        versions = []
        for filename in sorted(os.listdir(history_dir)):
            if filename.endswith(".json"):
                version_num = int(filename.replace("v", "").replace(".json", ""))
                filepath = os.path.join(history_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    versions.append({
                        "version": version_num,
                        "last_updated": data.get("last_updated", ""),
                        "file": filename,
                    })
                except (json.JSONDecodeError, IOError):
                    pass

        return versions

    def restore_version(self, version: int) -> bool:
        """Restore a previous profile version."""
        history_dir = os.path.join(os.path.dirname(self.profile_path), "history")
        history_file = os.path.join(history_dir, f"v{version}.json")

        if not os.path.exists(history_file):
            return False

        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.profile = UserProfile(**data)
            self.save()
            return True
        except (json.JSONDecodeError, TypeError, KeyError, IOError):
            return False

    def update_preference(self, category: str, key: str, value: str) -> None:
        """更新某个偏好"""
        if hasattr(self.profile, key):
            setattr(self.profile, key, value)
            self.save()

    def add_habit(self, habit_type: str, habit: str) -> None:
        """添加一个习惯"""
        if habit_type == "work":
            if habit not in self.profile.work_habits:
                self.profile.work_habits.append(habit)
        elif habit_type == "exercise":
            if habit not in self.profile.exercise_habits:
                self.profile.exercise_habits.append(habit)
        elif habit_type == "sleep":
            self.profile.sleep_schedule = habit
        elif habit_type == "work_schedule":
            self.profile.work_schedule = habit
        self.save()

    def add_relationship(self, name: str, relationship: str, notes: str = "") -> None:
        """添加人际关系"""
        entry = {"name": name, "relationship": relationship, "notes": notes}
        # 检查是否已存在同名关系
        for i, existing in enumerate(self.profile.relationships):
            if existing.get("name") == name and existing.get("relationship") == relationship:
                self.profile.relationships[i] = entry
                self.save()
                return
        self.profile.relationships.append(entry)
        self.save()

    def add_important_date(self, date: str, event: str, reminder: str = "") -> None:
        """添加重要日期"""
        entry = {"date": date, "event": event, "reminder": reminder}
        self.profile.important_dates.append(entry)
        self.save()

    def get_profile_summary(self) -> str:
        """获取档案摘要（用于 prompt 注入）"""
        parts = []
        p = self.profile

        if p.name:
            parts.append(f"用户称呼: {p.name}")
        if p.city:
            parts.append(f"所在城市: {p.city}")
        if p.occupation:
            parts.append(f"职业: {p.occupation}")
        if p.sleep_schedule:
            parts.append(f"作息: {p.sleep_schedule}")
        if p.work_habits:
            parts.append(f"工作习惯: {', '.join(p.work_habits)}")
        if p.food_preference:
            parts.append(f"饮食偏好: {p.food_preference}")
        if p.music_preference:
            parts.append(f"音乐偏好: {p.music_preference}")
        if p.relationships:
            rels = [f"{r['name']}({r['relationship']})" for r in p.relationships[:5]]
            parts.append(f"人际关系: {', '.join(rels)}")

        return "\n".join(parts) if parts else ""

    def to_dict(self) -> dict:
        """转换为字典"""
        return asdict(self.profile)
