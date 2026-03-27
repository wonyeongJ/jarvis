"""Jarvis 데스크톱 UI 에서 사용하는 스타일 상수 모음입니다.

시각 요소를 한곳에서 관리해 창 로직이나 위젯 로직을 수정하지 않고도
UI 톤을 조정할 수 있게 합니다.
"""

APP_TOOLTIP_STYLE = """
    QToolTip {
        background: #1E1F22;
        color: #DBDEE1;
        border: 1px solid #444;
        border-radius: 6px;
        padding: 5px 8px;
        font-size: 12px;
    }
"""

SIDEBAR_PANEL_STYLE = "background: #1E1F22;"
CHAT_PANEL_STYLE = "background: #313338;"
TRANSPARENT_BACKGROUND_STYLE = "background: transparent;"
VERTICAL_DIVIDER_STYLE = "background: #313338; border: none; max-width: 1px;"
HEADER_STYLE = "background: #313338; border-bottom: 1px solid #232428;"
INPUT_PANEL_STYLE = "background: #313338; border-top: 1px solid #232428;"
MESSAGE_CONTAINER_STYLE = "background: #313338;"
HORIZONTAL_SEPARATOR_STYLE = "color: #313338; margin: 6px 0;"

PRIMARY_BUTTON_STYLE = """
    QPushButton { background: #5865F2; color: white; border: none; border-radius: 8px; padding: 9px; font-size: 13px; font-weight: bold; }
    QPushButton:hover { background: #4752C4; }
    QPushButton:pressed { background: #3C45A5; }
"""

DANGER_OUTLINE_BUTTON_STYLE = """
    QPushButton { background: transparent; color: #ED4245; border: 1px solid #ED4245; border-radius: 8px; padding: 8px; font-size: 12px; }
    QPushButton:hover { background: #ED4245; color: white; }
"""

CHAT_LIST_STYLE = """
    QListWidget { background: transparent; color: #B5BAC1; border: none; font-size: 13px; outline: none; }
    QListWidget::item { padding: 7px 10px; border-radius: 6px; margin: 1px 0; }
    QListWidget::item:hover { background: #35373C; color: #DBDEE1; }
    QListWidget::item:selected { background: #404249; color: #FFFFFF; }
"""

CHAT_SCROLL_AREA_STYLE = """
    QScrollArea { background: #313338; border: none; }
    QScrollBar:vertical { background: #2B2D31; width: 6px; border-radius: 3px; }
    QScrollBar::handle:vertical { background: #1E1F22; border-radius: 3px; min-height: 30px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""

TITLE_LABEL_STYLE = "color: #FFFFFF; font-size: 15px; font-weight: bold;"
SECTION_LABEL_STYLE = "color: #72767D; font-size: 11px; font-weight: bold; padding: 2px 4px; letter-spacing: 1px;"
STATUS_BADGE_IDLE_STYLE = "QLabel { color: #72767D; background: #2B2D31; font-size: 11px; padding: 3px 10px; border-radius: 10px; }"
STATUS_BADGE_READY_STYLE = "QLabel { color: #57F287; background: #2B2D31; font-size: 11px; padding: 3px 10px; border-radius: 10px; }"
MODE_BADGE_STYLE = """
    QLabel { background: #ED4245; color: white; font-size: 11px;
             padding: 3px 10px; border-radius: 10px; font-weight: bold; }
"""

TEXT_EDIT_STYLE = """
    QTextEdit {
        background: #383A40;
        color: #DBDEE1;
        border: none;
        border-radius: 10px;
        padding: 10px 16px;
        font-size: 14px;
        font-family: 'Segoe UI';
    }
    QTextEdit:focus { background: #404249; }
    QScrollBar:vertical { width: 4px; background: transparent; }
    QScrollBar::handle:vertical { background: #555; border-radius: 2px; }
"""

PASTED_BADGE_STYLE = """
    QLabel {
        background: #5865F2;
        color: white;
        font-size: 11px;
        font-weight: bold;
        border-radius: 6px;
        padding: 2px 8px;
        font-family: 'Segoe UI';
    }
"""

REGEX_PANEL_TITLE_STYLE = "color: #FAA61A; font-size: 12px; font-weight: bold;"
REGEX_PANEL_LABEL_STYLE = "color: #DBDEE1; font-size: 12px;"
REGEX_RESULT_IDLE_STYLE = "color: #72767D; font-size: 12px; padding: 2px 4px;"
REGEX_RESULT_SUCCESS_STYLE = "color: #57F287; font-size: 12px; padding: 2px 4px;"
REGEX_RESULT_FAILURE_STYLE = "color: #ED4245; font-size: 12px; padding: 2px 4px;"
REGEX_RESULT_WARNING_STYLE = "color: #FAA61A; font-size: 12px; padding: 2px 4px;"
REGEX_PATTERN_INPUT_STYLE = """
    QLineEdit { background: #1E1F22; color: #FAA61A; border: 1px solid #444;
                border-radius: 6px; padding: 5px 10px; font-family: Consolas; font-size: 13px; }
"""
REGEX_TEST_INPUT_STYLE = """
    QLineEdit { background: #1E1F22; color: #DBDEE1; border: 1px solid #444;
                border-radius: 6px; padding: 5px 10px; font-size: 13px; }
"""

FILE_RESULTS_HEADER_STYLE = "color: #57F287; font-size: 12px; font-weight: bold; padding: 2px 4px;"
FILE_RESULTS_LIST_STYLE = """
    QListWidget {
        background: #2B2D31;
        color: #DBDEE1;
        border-radius: 12px;
        border: none;
        outline: none;
    }
    QListWidget::item { border: none; }
"""

CONTEXT_MENU_STYLE = """
    QMenu {
        background: #2B2D31;
        color: #DBDEE1;
        border: 1px solid #555;
        border-radius: 8px;
        padding: 4px;
        font-size: 13px;
    }
    QMenu::item {
        padding: 7px 20px;
        border-radius: 4px;
    }
    QMenu::item:selected { background: #5865F2; color: white; }
    QMenu::separator { height: 1px; background: #444; margin: 3px 8px; }
"""

TIMESTAMP_LEFT_STYLE = "color: #72767D; font-size: 10px; padding-left: 4px;"
TIMESTAMP_RIGHT_STYLE = "color: #72767D; font-size: 10px; padding-right: 4px;"

USER_MESSAGE_STYLE = """
    QLabel {
        background: #5865F2;
        color: #FFFFFF;
        padding: 10px 16px;
        border-radius: 18px;
        border-bottom-right-radius: 4px;
        font-size: 14px;
    }
"""

ASSISTANT_MESSAGE_STYLE = """
    QTextBrowser {
        background: #2B2D31;
        color: #DBDEE1;
        border-radius: 18px;
        border-bottom-left-radius: 4px;
        padding: 10px 16px;
        border: none;
        font-size: 14px;
    }
    QScrollBar { width: 0px; height: 0px; }
"""
