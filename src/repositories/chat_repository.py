"""채팅 로그를 파일로 저장하고 불러오는 저장소 계층입니다.

이 저장소는 각 대화를 JSON 파일 하나로 저장해,
PyInstaller 환경에서도 단순한 로컬 데이터 모델을 유지합니다.
"""

import datetime
import json
import os


DEFAULT_CHAT_TITLE = "새 대화"
FALLBACK_CHAT_TITLE = "대화"


def make_title(text, max_len=20):
    """첫 사용자 메시지를 바탕으로 짧은 제목을 생성합니다."""
    clean = text.replace("\n", " ").strip()
    return clean[:max_len] + ("..." if len(clean) > max_len else "")


class ChatRepository:
    """채팅 로그 JSON 파일을 읽고 쓰는 저장소입니다."""

    def __init__(self, save_dir):
        """채팅 파일을 저장할 디렉터리를 설정합니다."""
        self.save_dir = save_dir

    def _chat_path(self, chat_id):
        """채팅 ID 에 해당하는 파일 절대 경로를 반환합니다."""
        return os.path.join(self.save_dir, f"{chat_id}.json")

    def list_chat_files(self):
        """최신순으로 정렬된 채팅 파일명을 반환합니다."""
        return sorted(
            [file_name for file_name in os.listdir(self.save_dir) if file_name.endswith(".json")],
            reverse=True,
        )

    def save_chat(self, chat_id, title, messages):
        """채팅 로그를 저장하고 정규화된 payload 를 반환합니다."""
        if not messages:
            return None

        if not chat_id:
            chat_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        normalized_title = (title or DEFAULT_CHAT_TITLE).replace("\n", " ").strip()
        if normalized_title == DEFAULT_CHAT_TITLE:
            first_user = next((message["text"] for message in messages if message["role"] == "user"), "")
            normalized_title = make_title(first_user) if first_user else DEFAULT_CHAT_TITLE

        data = {
            "id": chat_id,
            "title": normalized_title,
            "messages": messages,
            "updated": datetime.datetime.now().isoformat(),
        }

        with open(self._chat_path(chat_id), "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

        return data

    def load_chat(self, chat_id):
        """지정한 ID 의 전체 채팅 로그를 불러옵니다."""
        path = self._chat_path(chat_id)
        if not os.path.exists(path):
            return None

        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    def load_chat_summaries(self):
        """사이드바 목록에 쓸 채팅 메타데이터를 불러옵니다."""
        chats = []
        for file_name in self.list_chat_files():
            path = os.path.join(self.save_dir, file_name)
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as file:
                    data = json.load(file)
                data["title"] = data.get("title", FALLBACK_CHAT_TITLE).replace("\n", " ").strip()
                chats.append(data)
            except Exception:
                continue
        return chats

    def delete_chat(self, chat_id):
        """지정한 채팅 로그 파일이 있으면 삭제합니다."""
        path = self._chat_path(chat_id)
        if os.path.exists(path):
            os.remove(path)
