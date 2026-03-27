"""Jarvis desktop application main window."""





import logging
import os
import re
import sys
import threading
import warnings

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QColor, QFont, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

try:
    import sip as _sip  # type: ignore
except ImportError:
    _sip = None

from app.chat_response_worker import ChatResponseWorker
from app.chat_session import ChatSession
from app.chat_stream_state import ChatStreamState
from core.paths import resource_path, writable_path
from core.settings import get_ollama_model_name
from core.request_routing import looks_like_error_report
from repositories.chat_repository import ChatRepository, DEFAULT_CHAT_TITLE, make_title
from services.file_action_service import copy_path_to_desktop, move_path_to_recycle_bin
from services.search_facade import is_everything_available, launch_everything, warm_up_rag_backend
from ui.styles import (
    APP_TOOLTIP_STYLE,
    CHAT_LIST_STYLE,
    CHAT_PANEL_STYLE,
    CHAT_SCROLL_AREA_STYLE,
    DANGER_OUTLINE_BUTTON_STYLE,
    HEADER_STYLE,
    HORIZONTAL_SEPARATOR_STYLE,
    INPUT_PANEL_STYLE,
    MESSAGE_CONTAINER_STYLE,
    MODE_BADGE_STYLE,
    PRIMARY_BUTTON_STYLE,
    SECTION_LABEL_STYLE,
    SIDEBAR_PANEL_STYLE,
    STATUS_BADGE_IDLE_STYLE,
    STATUS_BADGE_READY_STYLE,
    TITLE_LABEL_STYLE,
    TRANSPARENT_BACKGROUND_STYLE,
    VERTICAL_DIVIDER_STYLE,
)
from ui.widgets import (
    AutoExpandingTextEdit,
    ChatMessageBubble,
    FileSearchResultsBubble,
    RegexTestPanel,
)


os.environ["QT_LOGGING_RULES"] = "*.warning=false;*.critical=false"
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

OLLAMA_MODEL_NAME = get_ollama_model_name()
CHAT_STORAGE_DIR = writable_path("chats")

SYSTEM_PROMPT = """당신은 세계 최고 수준의 한국어 AI 어시스턴트이자 수석 엔지니어 비서입니다.

[페르소나 및 기본 태도]
- 너의 이름은 'Jarvis(자비스)'입니다. 사용자가 'jarvis' 또는 '자비스'라고 호명하면 본인으로 인식하세요.
- 사용자는 절대적으로 모셔야 할 "마스터"입니다. 모든 답변에서 불특정 다수 호칭("여러분" 등)을 금지하고, 충성스럽고 전문적인 태도로 응답하세요.
- 불필요한 서론/결론과 감정적 수사를 배제하고, 마스터의 시간을 아끼기 위해 본론과 해결책을 즉시 명확히 제공하세요.
- 마스터의 의도가 모호하다면 섣불리 예단하지 말고, "혹시 ~를 의미하시는 건가요?"라며 정중하게 확인하세요.

[답변 및 정보 제공 규칙]
- 항상 매끄럽고 자연스러운 한국어로 답변해야 합니다. 단위 변환 시에도 중복 표기('섭씨 °C 15°C')나 직역을 피하고 대한민국 표준(°C, km, kg 등)에 맞게 텍스트에 자연스럽게 녹여내세요.
- 제공된 웹 검색 결과가 있을 경우 오직 그 내용만을 토대로 답변하되, 정보의 신뢰성과 클릭 편의성을 위해 답변 끝에 반드시 마크다운 링크 형식("[웹사이트 제목](URL)")으로 출처를 명시하세요. 로컬 파일 검색 결과는 UI에 자체 표시되므로 파일 목록을 나열하지 마세요.
- 스스로 확신하지 못하는 정보(특히 날씨, 뉴스, 주가, 환율, 가짜 URL 등)는 절대 지어내거나 추측하지 마세요. 과거 블로그나 지난 뉴스의 검색 결과일 가능성을 염두에 두고, 실시간 정보가 명확하지 않다면 "정확한 실시간 정보는 도출되지 않았습니다"라고 보고하세요.
- 검색 결과가 비어 있을 경우 "검색 결과를 가져오지 못했습니다. 직접 확인해 주세요."라고만 답하세요.

[시니어 엔지니어링 (코드/기술 멘토)]
- Java, Spring Legacy, JSP, jQuery, JavaScript, CSS, HTML, Oracle SQL 관련 질문은 풍부한 경험을 가진 시니어 엔터프라이즈 개발자 관점에서 최적화된 코드로 안내하세요.
- 정규식 질문 시 패턴의 각 요소를 해부하여 설명하고, Java Pattern.compile 예시와 테스트 케이스(매칭/비매칭)를 구체적으로 보여주세요.
- 취약점(Security)이나 성능 병목이 예상되는 옛날 방식(Bad Smell) 코드는 지양하고, 능동적으로 더 나은 현대적 대안(Best Practice)을 시니어로서 마스터에게 제안하세요.
- NullPointerException이나 DB 락(Lock) 같은 잠재적 문제점을 미리 파악하고, 방어 로직을 주석으로 달아 마스터가 실무에서 실수하지 않도록 조언하세요.

[마크다운(Markdown) 및 UI 구조화]
- 설명이 길어질 경우 줄글로만 나열하지 말고, 번호 목록(1, 2)과 불릿 포인트(-, *)를 적극 활용하여 시인성을 극대화하세요.
- 핵심 키워드, 주요 개념, 파일명, 변수명에는 **볼드체**와 `인라인 코드`를 반드시 적용해 마스터가 한눈에 스캐닝할 수 있게 만드세요.
- 코드 블록 앞뒤로 언어 태그(```java 등)를 명시하고, 블록 직후 코드의 동작을 짧고 명쾌하게 요약해서 덧붙이세요.
"""

WELCOME_MESSAGE = """
안녕하십니까!

저는 **Jarvis**, 마스터의 충실한 종입니다.

하명 하십시오.
"""


class JarvisMainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        """Initialize window state and timers."""
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.resize(1200, 800)

        self.chat_repository = ChatRepository(CHAT_STORAGE_DIR)
        self.chat_session = ChatSession(self.chat_repository)
        self.stream_state = ChatStreamState()
        self.response_worker = None
        self._last_chat_files = set()
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setSingleShot(True)
        self._stream_flush_timer.timeout.connect(self._flush_stream_update)

        self._build_ui()
        self.reload_chat_list()

        threading.Thread(target=launch_everything, daemon=True).start()
        threading.Thread(target=warm_up_rag_backend, daemon=True).start()

        self.everything_timer = QTimer()
        self.everything_timer.timeout.connect(self._update_everything_status)
        self.everything_timer.start(2000)

        self.chat_list_watcher_timer = QTimer()
        self.chat_list_watcher_timer.timeout.connect(self._reload_chat_list_if_files_changed)
        self.chat_list_watcher_timer.start(5000)

        self.start_new_chat()

    def _update_everything_status(self):
        """Reflect Everything readiness in the header badge."""

        def check_status():
            ready = is_everything_available()
            if ready:
                self.everything_badge.setText("🔎 PC 검색 준비 완료")
                self.everything_badge.setStyleSheet(STATUS_BADGE_READY_STYLE)
                self.everything_timer.stop()
            else:
                self.everything_badge.setText("⏳ PC 검색 준비 중")

        threading.Thread(target=check_status, daemon=True).start()

    def _show_chat_list_tooltip(self, event):
        """Show the full chat title as a tooltip."""
        item = self.chat_list.itemAt(event.pos())
        if item:
            QToolTip.showText(
                self.chat_list.mapToGlobal(event.pos()),
                item.data(Qt.UserRole + 1) or item.text(),
                self.chat_list,
            )
        else:
            QToolTip.hideText()
        QListWidget.mouseMoveEvent(self.chat_list, event)

    def _reload_chat_list_if_files_changed(self):
        """Reload the sidebar when chat files changed."""
        current_files = set(self.chat_repository.list_chat_files())
        if current_files != self._last_chat_files:
            self._last_chat_files = current_files
            self.reload_chat_list()

    def _build_ui(self):
        """Build the main two-column layout."""
        root_widget = QWidget()
        self.setCentralWidget(root_widget)

        root_layout = QHBoxLayout(root_widget)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(self._build_sidebar_panel())

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setStyleSheet(VERTICAL_DIVIDER_STYLE)
        root_layout.addWidget(divider)
        root_layout.addWidget(self._build_chat_panel())

    def _build_sidebar_panel(self):
        """Build the sidebar panel."""
        sidebar_widget = QWidget()
        sidebar_widget.setFixedWidth(240)
        sidebar_widget.setStyleSheet(SIDEBAR_PANEL_STYLE)

        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(10, 16, 10, 12)
        sidebar_layout.setSpacing(4)
        sidebar_layout.addWidget(self._build_sidebar_title())

        new_chat_button = QPushButton("+ 새 채팅")
        new_chat_button.setCursor(Qt.PointingHandCursor)
        new_chat_button.setStyleSheet(PRIMARY_BUTTON_STYLE)
        new_chat_button.clicked.connect(self.start_new_chat)
        sidebar_layout.addWidget(new_chat_button)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet(HORIZONTAL_SEPARATOR_STYLE)
        sidebar_layout.addWidget(separator)

        list_label = QLabel("채팅 목록")
        list_label.setStyleSheet(SECTION_LABEL_STYLE)
        sidebar_layout.addWidget(list_label)

        self.chat_list = QListWidget()
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_list.setMouseTracking(True)
        self.chat_list.setTextElideMode(Qt.ElideRight)
        self.chat_list.setWordWrap(False)
        self.chat_list.setUniformItemSizes(True)
        self.chat_list.setStyleSheet(CHAT_LIST_STYLE)
        self.chat_list.itemClicked.connect(self.load_selected_chat)
        self.chat_list.mouseMoveEvent = self._show_chat_list_tooltip
        sidebar_layout.addWidget(self.chat_list)

        delete_chat_button = QPushButton("선택 채팅 삭제")
        delete_chat_button.setCursor(Qt.PointingHandCursor)
        delete_chat_button.setStyleSheet(DANGER_OUTLINE_BUTTON_STYLE)
        delete_chat_button.clicked.connect(self.delete_selected_chat)
        sidebar_layout.addWidget(delete_chat_button)
        return sidebar_widget

    def _build_sidebar_title(self):
        """Build sidebar title area."""
        title_widget = QWidget()
        title_widget.setStyleSheet(TRANSPARENT_BACKGROUND_STYLE)
        title_layout = QHBoxLayout(title_widget)
        title_layout.setContentsMargins(0, 0, 0, 8)
        title_layout.setSpacing(8)

        icon_path = resource_path("images/jarvis_icon.jpg")
        if os.path.exists(icon_path):
            icon_label = QLabel()
            pixmap = QPixmap(icon_path).scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label.setPixmap(pixmap)
            icon_label.setStyleSheet(TRANSPARENT_BACKGROUND_STYLE)
            title_layout.addWidget(icon_label)

        title_label = QLabel("Jarvis")
        title_label.setStyleSheet(TITLE_LABEL_STYLE)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        return title_widget

    def _build_chat_panel(self):
        """Build the right chat panel."""
        chat_panel = QWidget()
        chat_panel.setStyleSheet(CHAT_PANEL_STYLE)

        chat_panel_layout = QVBoxLayout(chat_panel)
        chat_panel_layout.setContentsMargins(0, 0, 0, 0)
        chat_panel_layout.setSpacing(0)
        chat_panel_layout.addWidget(self._build_chat_header())
        chat_panel_layout.addWidget(self._build_message_scroll_area(), 1)
        chat_panel_layout.addWidget(self._build_input_panel(), 0)
        return chat_panel

    def _build_chat_header(self):
        """Build the header with title and status badges."""
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(HEADER_STYLE)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)

        self.chat_title_label = QLabel(DEFAULT_CHAT_TITLE)
        self.chat_title_label.setWordWrap(False)
        self.chat_title_label.setMaximumWidth(500)
        self.chat_title_label.setStyleSheet(TITLE_LABEL_STYLE)
        header_layout.addWidget(self.chat_title_label)
        header_layout.addStretch()

        self.everything_badge = QLabel("⏳ PC 검색 준비 중")
        self.everything_badge.setStyleSheet(STATUS_BADGE_IDLE_STYLE)
        header_layout.addWidget(self.everything_badge)

        model_badge = QLabel(OLLAMA_MODEL_NAME)
        model_badge.setStyleSheet(STATUS_BADGE_IDLE_STYLE)
        header_layout.addWidget(model_badge)
        return header

    def _build_message_scroll_area(self):
        """Build the message scroll area."""
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(CHAT_SCROLL_AREA_STYLE)

        self.message_container = QWidget()
        self.message_container.setStyleSheet(MESSAGE_CONTAINER_STYLE)
        self.chat_layout = QVBoxLayout(self.message_container)
        self.chat_layout.setContentsMargins(16, 16, 16, 16)
        self.chat_layout.setSpacing(8)
        self.chat_layout.addStretch()
        self.scroll.setWidget(self.message_container)
        return self.scroll

    def _build_input_panel(self):
        """Build the bottom input area."""
        self.input_area = QWidget()
        self.input_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.input_area.setStyleSheet(INPUT_PANEL_STYLE)

        input_layout = QHBoxLayout(self.input_area)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(0)

        self.input = AutoExpandingTextEdit()
        self.input.submit.connect(self.handle_send_message)
        input_layout.addWidget(self.input)
        return self.input_area

    def start_new_chat(self):
        """Start a new chat session."""
        if self.chat_session.has_messages():
            self.save_current_chat()
        self.chat_session.reset()
        self.clear_message_area()
        self.chat_title_label.setText(DEFAULT_CHAT_TITLE)
        self.chat_list.clearSelection()
        self.append_assistant_message(WELCOME_MESSAGE, save_to_session=False)

    def append_user_message(self, text):
        """Append a user message bubble."""
        bubble = ChatMessageBubble(text, True)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.chat_session.append_user_message(text)
        self.scroll_to_bottom()

    def append_assistant_message(self, text, save_to_session=True):
        """Append an assistant message bubble."""
        bubble = ChatMessageBubble(text, False)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        if save_to_session and text != "...":
            self.chat_session.append_assistant_message(text)
        self.scroll_to_bottom()

    def clear_message_area(self):
        """Clear the message area and keep the spacer."""
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def scroll_to_bottom(self):
        """Scroll to the bottom after layout updates."""
        QTimer.singleShot(
            120,
            lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()),
        )

    def handle_send_message(self):
        """Submit the current input and start the response worker."""
        text = self.input.toPlainText().strip()
        if not text:
            return

        self.input.clear()
        self.input.setEnabled(False)

        if looks_like_error_report(text) and len(text) > 50:
            self._show_mode_badge("🧯 오류 분석 모드")

        self.append_user_message(text)
        self.stream_state.start_stream(self._append_temporary_assistant_bubble("..."))

        if len(self.chat_session.messages) == 1:
            title = make_title(text)
            self.chat_title_label.setText(title)
            self.save_current_chat()
            self._insert_chat_list_item_at_top(self.chat_session.current_chat_id, title)

        self.response_worker = ChatResponseWorker(
            list(self.chat_session.messages),
            OLLAMA_MODEL_NAME,
            SYSTEM_PROMPT,
        )
        self.response_worker.finished.connect(self.handle_response_finished)
        self.response_worker.search_status.connect(self.handle_search_status)
        self.response_worker.streaming.connect(self.handle_stream_token)
        self.response_worker.pc_result.connect(self.handle_pc_search_results)
        self.response_worker.pc_failed.connect(self.handle_pc_search_failure)
        self.response_worker.file_action.connect(self.handle_file_action_request)
        self.response_worker.start()

    def _remove_pending_status_bubble(self):
        """Remove the pending status bubble and reset stream state."""
        pending_item = self.chat_layout.itemAt(self.chat_layout.count() - 2)
        pending_widget = pending_item.widget() if pending_item else None
        if pending_widget:
            pending_widget.setParent(None)
        self.stream_state.reset_stream()

    def _restore_input_ready_state(self):
        """Restore the input area after a response finishes."""
        self.input.setEnabled(True)
        self.input.setFocus()

    def _flush_stream_update(self):
        """Flush accumulated stream tokens into the bubble."""
        if not self.stream_state.has_active_bubble(_sip):
            return
        try:
            self.stream_state.render_to_bubble()
        except RuntimeError:
            self.stream_state.reset_stream()
            return
        if self.stream_state.should_scroll_after_chunk(chunk_size=120):
            self.scroll_to_bottom()

    def handle_stream_token(self, token):
        """Buffer stream tokens briefly for smoother rendering."""
        self.stream_state.append_chunk(token)
        if not self._stream_flush_timer.isActive():
            self._stream_flush_timer.start(35)

    def handle_search_status(self, message):
        """Show a temporary search status bubble."""
        self._remove_pending_status_bubble()
        self.stream_state.start_stream(self._append_temporary_assistant_bubble(message))

    def handle_pc_search_results(self, items):
        """Render PC search results as a result bubble."""
        self._remove_pending_status_bubble()
        bubble = FileSearchResultsBubble(items)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.scroll_to_bottom()
        self._restore_input_ready_state()
        self.chat_session.append_assistant_message(
            f"[🔎 PC 파일 검색 결과 {len(items)}개를 화면에 표시했습니다. 번호로 파일 열기, 삭제, 복사를 진행할 수 있습니다.]"
        )
        self.save_current_chat()

    def handle_pc_search_failure(self, message):
        """Show a normal assistant message for PC search failure."""
        self._remove_pending_status_bubble()
        self.append_assistant_message(message)
        self._restore_input_ready_state()

    def handle_file_action_request(self, action, path):
        """Execute a follow-up file action requested by number."""
        self._remove_pending_status_bubble()
        self._restore_input_ready_state()

        name = os.path.basename(path)

        if action == "delete":
            reply = QMessageBox.question(
                self,
                "삭제 확인",
                f"'{name}' 파일을 휴지통으로 이동하시겠습니까?\n\n{path}",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                try:
                    move_path_to_recycle_bin(path)
                    self.append_assistant_message(f"휴지통으로 이동했습니다.\n{path}")
                except Exception as error:
                    self.append_assistant_message(f"삭제에 실패했습니다.\n{error}")
            else:
                self.append_assistant_message("삭제를 취소했습니다.")

        elif action == "copy":
            try:
                destination = copy_path_to_desktop(path)
                self.append_assistant_message(f"바탕화면으로 복사했습니다.\n{destination}")
            except Exception as error:
                self.append_assistant_message(f"복사에 실패했습니다.\n{error}")

    def _show_mode_badge(self, text):
        """Show a short mode badge in the header."""
        badge = QLabel(text)
        badge.setStyleSheet(MODE_BADGE_STYLE)
        header_layout = self.chat_title_label.parent().layout()
        if header_layout:
            header_layout.insertWidget(1, badge)
            QTimer.singleShot(2000, badge.deleteLater)

    def _append_temporary_assistant_bubble(self, text):
        """Append a temporary bubble for loading or streaming."""
        bubble = ChatMessageBubble(text, False)
        bubble.setProperty("temp", True)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.scroll_to_bottom()
        return bubble

    def handle_response_finished(self, response):
        """Finalize the streaming response and save it."""
        if self._stream_flush_timer.isActive():
            self._stream_flush_timer.stop()

        if self.stream_state.bubble:
            self.stream_state.render_to_bubble(response)
            self.stream_state.reset_stream()
            self.chat_session.append_assistant_message(response)
        else:
            self._remove_pending_status_bubble()
            self.append_assistant_message(response)

        if getattr(self.response_worker, "regex_mode", False):
            pattern = self._extract_regex_from_response(response)
            panel = RegexTestPanel(pattern)
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, panel)

        self.scroll_to_bottom()
        self._restore_input_ready_state()
        self.save_current_chat()
        self.reload_chat_list()

    def _extract_regex_from_response(self, text):
        """Extract a regex pattern from the response text."""
        compiled_pattern_match = re.search(r'Pattern\.compile\("([^"]+)"\)', text)
        if compiled_pattern_match:
            return compiled_pattern_match.group(1)

        inline_code_match = re.search(r'([^\n]{3,80})', text)
        if inline_code_match:
            return inline_code_match.group(1)
        return ""

    def save_current_chat(self):
        """Persist the current chat and reflect title and id."""
        data = self.chat_session.persist(self.chat_title_label.text())
        if data:
            self.chat_session.current_chat_id = data["id"]
            self.chat_title_label.setText(data["title"])

    def _insert_chat_list_item_at_top(self, chat_id, title):
        """Insert a chat list item at the top if it does not already exist."""
        for index in range(self.chat_list.count()):
            item = self.chat_list.item(index)
            if item and item.data(Qt.UserRole) == chat_id:
                return
        item = QListWidgetItem(title)
        item.setData(Qt.UserRole, chat_id)
        self.chat_list.insertItem(0, item)
        self.chat_list.setCurrentRow(0)

    def reload_chat_list(self):
        """Reload the sidebar from saved chat summaries."""
        self.chat_list.clear()
        for data in self.chat_repository.load_chat_summaries():
            title = data.get("title", DEFAULT_CHAT_TITLE)
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, data["id"])
            item.setData(Qt.UserRole + 1, title)
            item.setToolTip(title)
            self.chat_list.addItem(item)
            if data["id"] == self.chat_session.current_chat_id:
                item.setSelected(True)
                item.setBackground(QColor("#404249"))
                item.setForeground(QColor("#FFFFFF"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)

    def load_selected_chat(self, item):
        """Load the selected chat back into the UI."""
        chat_id = item.data(Qt.UserRole)
        if self.chat_session.has_messages():
            self.save_current_chat()
        data = self.chat_session.load(chat_id)
        if not data:
            self.reload_chat_list()
            return

        self.chat_title_label.setText(self.chat_session.title_or_default(data))
        self.clear_message_area()
        for message in self.chat_session.messages:
            bubble = ChatMessageBubble(message["text"], message["role"] == "user")
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self.scroll_to_bottom()
        self.reload_chat_list()

    def delete_selected_chat(self):
        """Delete the selected chat after confirmation."""
        selected = self.chat_list.currentItem()
        if not selected:
            if not self.chat_session.current_chat_id:
                QMessageBox.information(self, "알림", "삭제할 채팅이 없습니다.")
                return
            chat_id = self.chat_session.current_chat_id
            chat_title = self.chat_title_label.text()
        else:
            chat_id = selected.data(Qt.UserRole)
            chat_title = selected.text()

        reply = QMessageBox.question(
            self,
            "삭제 확인",
            f"'{chat_title}' 채팅을 삭제하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            was_current_chat = self.chat_session.current_chat_id == chat_id
            self.chat_session.delete(chat_id)
            if was_current_chat:
                self.clear_message_area()
                self.chat_title_label.setText(DEFAULT_CHAT_TITLE)
                self.start_new_chat()
            self.reload_chat_list()


def main():
    """Create and run the main application window."""
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    os.environ["QT_LOGGING_RULES"] = "*.warning=false"
    app.setStyleSheet(APP_TOOLTIP_STYLE)
    window = JarvisMainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
