"""활성 대화의 세션 상태를 관리하는 모듈입니다.

이 모듈은 메인 윈도우가 화면 갱신에만 집중할 수 있도록,
현재 대화 ID 와 메시지 목록을 메모리에서 분리해 관리합니다.
"""

import datetime

from repositories.chat_repository import ChatRepository, DEFAULT_CHAT_TITLE


class ChatSession:
    """현재 대화의 식별자와 메시지 목록을 관리합니다."""

    def __init__(self, chat_repository: ChatRepository):
        """지정한 저장소를 사용하는 채팅 세션을 생성합니다."""
        self.chat_repository = chat_repository
        self.current_chat_id = self._generate_chat_id()
        self.messages = []

    def _generate_chat_id(self):
        """새 대화에 사용할 시간 기반 ID 를 생성합니다."""
        return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    def reset(self):
        """현재 세션을 비우고 새 대화를 시작할 준비를 합니다."""
        self.current_chat_id = self._generate_chat_id()
        self.messages = []

    def has_messages(self):
        """현재 세션에 저장할 메시지가 있는지 반환합니다."""
        return bool(self.messages)

    def append_user_message(self, text):
        """사용자 메시지를 현재 대화에 추가합니다."""
        self.messages.append({"role": "user", "text": text})

    def append_assistant_message(self, text):
        """어시스턴트 메시지를 현재 대화에 추가합니다."""
        self.messages.append({"role": "assistant", "text": text})

    def persist(self, title):
        """현재 대화를 저장소에 저장하고 정규화된 결과를 반환합니다."""
        return self.chat_repository.save_chat(
            self.current_chat_id,
            title,
            self.messages,
        )

    def load(self, chat_id):
        """저장된 대화를 세션 상태로 불러옵니다."""
        data = self.chat_repository.load_chat(chat_id)
        if not data:
            return None
        self.current_chat_id = data["id"]
        self.messages = data["messages"]
        return data

    def delete(self, chat_id):
        """저장된 대화를 삭제하고 현재 세션과 같으면 초기화합니다."""
        self.chat_repository.delete_chat(chat_id)
        if self.current_chat_id == chat_id:
            self.reset()

    def title_or_default(self, data):
        """불러온 대화 데이터에서 화면용 제목을 반환합니다."""
        return data.get("title", DEFAULT_CHAT_TITLE).replace("\n", " ").strip()
