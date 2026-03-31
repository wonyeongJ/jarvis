"""스트리밍 응답 상태를 담는 컨테이너입니다.

메인 윈도우는 이 객체를 통해 임시 말풍선, 누적 텍스트,
토큰 수를 관리합니다.
"""


class ChatStreamState:
    """현재 스트리밍 말풍선과 누적 텍스트(버퍼)를 관리합니다."""

    def __init__(self):
        """활성 스트림이 없는 초기 상태로 준비합니다."""
        self.bubble = None
        self.text = ""  # LLM으로부터 받은 전체 텍스트 (버퍼)
        self.displayed_text = ""  # 현재 화면에 출력된 텍스트
        self.token_count = 0

    def start_stream(self, bubble):
        """임시 말풍선을 연결하고 스트림 누적 상태를 초기화합니다."""
        self.bubble = bubble
        self.text = ""
        self.displayed_text = ""
        self.token_count = 0

    def reset_stream(self):
        """활성 스트림 참조와 카운터를 모두 비웁니다."""
        self.bubble = None
        self.text = ""
        self.displayed_text = ""
        self.token_count = 0

    def append_chunk(self, token):
        """새로 들어온 스트리밍 토큰을 누적 버퍼에 추가합니다."""
        self.text += token
        self.token_count += 1

    def consume_characters(self, count):
        """버퍼에서 지정된 수만큼 문자를 꺼내 표시용 텍스트에 추가합니다."""
        pending_text = self.text[len(self.displayed_text):]
        to_add = pending_text[:count]
        self.displayed_text += to_add
        return len(to_add) > 0

    def is_all_displayed(self):
        """버퍼의 모든 내용이 화면에 표시되었는지 확인합니다."""
        return len(self.text) <= len(self.displayed_text)

    def has_active_bubble(self, sip_module=None):
        """임시 응답 말풍선이 아직 살아 있는지 확인합니다."""
        if self.bubble is None:
            return False
        if sip_module is None:
            return True
        try:
            return not sip_module.isdeleted(self.bubble)
        except Exception:
            return False

    def render_to_bubble(self, override_text=None):
        """표시용 텍스트를 현재 임시 말풍선에 반영합니다."""
        if self.bubble is None:
            return
        content = override_text if override_text is not None else self.displayed_text
        self.bubble.update_text(content)

    def should_scroll_after_chunk(self, chunk_size=30):
        """일정 토큰 수마다 자동 스크롤할지 결정합니다."""
        return self.token_count > 0 and self.token_count % chunk_size == 0

