from __future__ import annotations

import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal, QTimer, QUrl
from PySide6.QtGui import QAction
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .audio_meta import analyze_audio, format_audio_analysis, format_duration
from .db import PlanCategory, SoundFinderDB
from .handoff import CURRENT_PLAN_PATH, read_plan_file, write_plan_file
from .indexer import score_file, search_audio_files, scan_library
from .local_llm import (
    DEFAULT_OLLAMA_URL,
    DEFAULT_OPENAI_URL,
    DEFAULT_REMOTE_MODEL,
    DEFAULT_REMOTE_URL,
    LocalModelConfig,
    config_from_mapping,
    generate_requirement_plan,
    settings_from_config,
)
from .planner import suggest_title
from .recipe import (
    STYLE_LABELS,
    build_recipe_for_category,
    make_recommendations,
    next_style_for_category,
    recommend_layer,
    similar_replacement,
)
from .reaper_tracks import create_or_update_reaper_project, reaper_exe_path
from .soundly_export import export_soundly_search_sheet
from .widgets import DragFileLabel, ResultTable, WaveformView


class ScanWorker(QObject):
    progress = Signal(dict, str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, db_path: Path, root: Path, mode: str = "incremental") -> None:
        super().__init__()
        self.db_path = db_path
        self.root = root
        self.mode = mode

    def run(self) -> None:
        try:
            db = SoundFinderDB(self.db_path)
            stats = scan_library(db, self.root, self.progress.emit, mode=self.mode)
            self.finished.emit(stats)
        except Exception as exc:  # pragma: no cover - UI worker boundary
            self.failed.emit(str(exc))


class AudioTaskWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, db_path: Path, task: str, payload: dict[str, Any]) -> None:
        super().__init__()
        self.db_path = db_path
        self.task = task
        self.payload = payload

    def run(self) -> None:
        try:
            db = SoundFinderDB(self.db_path)
            if self.task == "confirm_search":
                result = self.run_confirm_search(db)
            elif self.task == "change_recipe":
                result = self.run_change_recipe(db)
            elif self.task == "research_layer":
                result = self.run_research_layer(db)
            elif self.task == "replace_layer_recipe":
                result = self.run_replace_layer_recipe(db)
            elif self.task == "local_requirement":
                result = self.run_local_requirement(db)
            else:
                raise ValueError(f"未知任务：{self.task}")
            self.finished.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def history_title(self, source: str, recommendations: list[dict[str, Any]]) -> str:
        layer_names = [item.get("layer_name", "Layer") for item in recommendations]
        source_label = {
            "recommend": "推荐组合",
            "recipe_changed": "整体配方",
            "layer_researched": "重搜 Layer",
            "layer_recipe_changed": "替换 Layer",
        }.get(source, source)
        return f"{source_label} / {len(layer_names)}层 / {' + '.join(layer_names[:4])}"

    def save_combo_snapshot(
        self,
        db: SoundFinderDB,
        session_id: int,
        category: dict[str, Any],
        source: str,
        recommendations: list[dict[str, Any]],
    ) -> None:
        if not recommendations:
            return
        db.save_combo_history(
            session_id,
            category["id"],
            title=self.history_title(source, recommendations),
            source=source,
            recipe_style=str(category.get("recipe_style", "realistic_tactile")),
            recipe=category.get("recipe", []),
            recommendations=recommendations,
            results=db.list_results(session_id, category["id"], db.get_setting("library_root", "")),
        )

    def recommendation_list_with_layer(
        self,
        db: SoundFinderDB,
        session_id: int,
        category: dict[str, Any],
        layer: dict[str, Any],
        new_recommendation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        recs = db.list_recommendations(session_id, category["id"], db.get_setting("library_root", ""))
        rec_by_layer = {rec["layer_name"]: rec for rec in recs}
        rec_by_layer[layer.get("name", "Layer")] = new_recommendation

        ordered: list[dict[str, Any]] = []
        for recipe_layer in category.get("recipe", []):
            rec = rec_by_layer.get(recipe_layer.get("name", ""))
            if not rec:
                continue
            ordered.append(
                {
                    "layer_name": rec["layer_name"],
                    "layer_role": rec["layer_role"],
                    "audio_file_id": rec["audio_file_id"],
                    "score": rec["score"],
                    "reason": rec["reason"],
                }
            )
        return ordered

    def run_confirm_search(self, db: SoundFinderDB) -> dict[str, Any]:
        session_id = int(self.payload["session_id"])
        requirement = str(self.payload["requirement"])
        plan: list[PlanCategory] = self.payload["plan"]
        first_category_id, total_saved = self.replace_and_search_plan(
            db, session_id, requirement, plan, limit_per_category=self.payload.get("result_limit")
        )
        db.set_setting("last_session_id", str(session_id))
        return {
            "session_id": session_id,
            "select_category_id": first_category_id,
            "message": f"搜索完成，共保存 {total_saved} 条结果。",
        }

    def run_local_requirement(self, db: SoundFinderDB) -> dict[str, Any]:
        requirement = str(self.payload["requirement"])
        auto_search = bool(self.payload.get("auto_search", True))
        config = config_from_mapping(dict(self.payload.get("config") or {}))
        self.progress.emit("本地模型正在拆解需求...")
        generated = generate_requirement_plan(requirement, config)
        session_id = db.create_session(generated.title, generated.requirement)
        write_plan_file(CURRENT_PLAN_PATH, generated.title, generated.requirement, generated.categories)

        if not auto_search:
            db.replace_plan(session_id, generated.requirement, generated.categories)
            db.set_setting("last_session_id", str(session_id))
            warning = f" {generated.warning}" if generated.warning else ""
            route_note = f" 路由：{generated.route_reason}" if generated.route_reason else ""
            return {
                "session_id": session_id,
                "select_category_id": None,
                "message": f"已由 {generated.source} 生成方案，未自动搜索。{route_note}{warning}".strip(),
            }

        first_category_id, total_saved = self.replace_and_search_plan(
            db,
            session_id,
            generated.requirement,
            generated.categories,
            limit_per_category=self.payload.get("result_limit"),
        )
        db.set_setting("last_session_id", str(session_id))
        warning = f" {generated.warning}" if generated.warning else ""
        route_note = f" 路由：{generated.route_reason}" if generated.route_reason else ""
        return {
            "session_id": session_id,
            "select_category_id": first_category_id,
            "message": f"已由 {generated.source} 拆解并完成搜索，共保存 {total_saved} 条结果。{route_note}{warning}".strip(),
        }

    def replace_and_search_plan(
        self,
        db: SoundFinderDB,
        session_id: int,
        requirement: str,
        plan: list[PlanCategory],
        limit_per_category: int | None = None,
    ) -> tuple[int | None, int]:
        category_ids = db.replace_plan(session_id, requirement, plan)
        first_category_id: int | None = None
        total_saved = 0

        # Per-category result count is user-controlled (the "每栏条数" box). Results are
        # ranked best-first (most keywords hit), so each category keeps its top N.
        try:
            per_category_limit = int(limit_per_category) if limit_per_category else 80
        except (TypeError, ValueError):
            per_category_limit = 80
        per_category_limit = max(1, per_category_limit)

        for index, category in enumerate(plan):
            category_id = category_ids[index]
            if first_category_id is None and category.include:
                first_category_id = category_id
            self.progress.emit(f"搜索 {index + 1}/{len(plan)}：{category.name}")
            results = search_audio_files(db, [category], limit_per_category=per_category_limit).get(0, [])
            db.save_results(session_id, category_id, results)
            total_saved += len(results)
            if not category.include:
                continue

            category_dict = {
                "id": category_id,
                "name": category.name,
                "direction": category.direction,
                "keywords": category.keywords,
                "include": category.include,
                "recipe": category.recipe,
                "recipe_style": category.recipe_style,
            }
            recommendations = make_recommendations(category_dict, results)
            if recommendations:
                db.save_recommendations(session_id, category_id, recommendations, "recommend")
                self.save_combo_snapshot(db, session_id, category_dict, "recommend", recommendations)

        return first_category_id, total_saved

    def run_change_recipe(self, db: SoundFinderDB) -> dict[str, Any]:
        session_id = int(self.payload["session_id"])
        category = dict(self.payload["category"])
        new_style = str(self.payload["new_style"])
        self.progress.emit(f"切换整体配方：{category['name']}")
        new_recipe = build_recipe_for_category(category, new_style)
        db.update_category_recipe(category["id"], recipe=new_recipe, recipe_style=new_style)

        plan_category = PlanCategory(
            category["name"],
            category["direction"],
            category["keywords"],
            category["include"],
            new_recipe,
            new_style,
        )
        results = search_audio_files(db, [plan_category]).get(0, [])
        db.replace_category_results(session_id, category["id"], results)

        updated_category = dict(category)
        updated_category["recipe"] = new_recipe
        updated_category["recipe_style"] = new_style
        recommendations = make_recommendations(updated_category, results)
        db.save_recommendations(session_id, category["id"], recommendations, "recipe_changed")
        self.save_combo_snapshot(db, session_id, updated_category, "recipe_changed", recommendations)
        return {
            "session_id": session_id,
            "select_category_id": category["id"],
            "message": f"{category['name']} 已切换为：{STYLE_LABELS.get(new_style, new_style)}",
        }

    def run_research_layer(self, db: SoundFinderDB) -> dict[str, Any]:
        session_id = int(self.payload["session_id"])
        category = dict(self.payload["category"])
        layer = dict(self.payload["layer"])
        self.progress.emit(f"重搜 Layer：{category['name']} / {layer.get('name', 'Layer')}")
        plan_category = PlanCategory(
            category["name"],
            layer.get("role", ""),
            [],
            True,
            [layer],
            str(category.get("recipe_style", "realistic_tactile")),
        )
        layer_results = search_audio_files(db, [plan_category]).get(0, [])
        if not layer_results:
            raise ValueError("当前 Layer 的关键词没有搜到可用素材。")
        db.merge_category_results(session_id, category["id"], layer_results)

        existing = db.list_recommendations(session_id, category["id"], db.get_setting("library_root", ""))
        avoid_ids = {
            rec["audio_file_id"]
            for rec in existing
            if rec.get("layer_name") != layer.get("name")
        }
        new_rec = recommend_layer(layer, layer_results, avoid_ids)
        if new_rec is None:
            raise ValueError("当前 Layer 的搜索结果不足以生成推荐。")
        updated = self.recommendation_list_with_layer(db, session_id, category, layer, new_rec)
        db.save_recommendations(session_id, category["id"], updated, "layer_researched")
        self.save_combo_snapshot(db, session_id, category, "layer_researched", updated)
        return {
            "session_id": session_id,
            "select_category_id": category["id"],
            "message": f"{category['name']} / {layer.get('name', 'Layer')} 已单独重搜并更新组合。",
        }

    def run_replace_layer_recipe(self, db: SoundFinderDB) -> dict[str, Any]:
        session_id = int(self.payload["session_id"])
        category = dict(self.payload["category"])
        layer = dict(self.payload["layer"])
        layer_index = int(self.payload["layer_index"])
        new_style = str(self.payload["new_style"])
        self.progress.emit(f"替换 Layer 配方：{category['name']} / 第 {layer_index + 1} 层")

        recipe = list(category.get("recipe", []))
        variant_recipe = build_recipe_for_category(category, new_style)
        if layer_index < len(variant_recipe):
            replacement_layer = variant_recipe[layer_index]
        else:
            replacement_layer = dict(layer)
            replacement_layer["keywords"] = list(layer.get("keywords", [])) + list(category.get("keywords", []))

        recipe[layer_index] = replacement_layer
        custom_style = f"custom:{new_style}"
        db.update_category_recipe(category["id"], recipe=recipe, recipe_style=custom_style)

        updated_category = dict(category)
        updated_category["recipe"] = recipe
        updated_category["recipe_style"] = custom_style
        plan_category = PlanCategory(
            updated_category["name"],
            replacement_layer.get("role", ""),
            [],
            True,
            [replacement_layer],
            custom_style,
        )
        layer_results = search_audio_files(db, [plan_category]).get(0, [])
        if layer_results:
            db.merge_category_results(session_id, category["id"], layer_results)
        current_results = db.list_results(session_id, category["id"], db.get_setting("library_root", ""))
        existing = db.list_recommendations(session_id, category["id"], db.get_setting("library_root", ""))
        avoid_ids = {
            rec["audio_file_id"]
            for rec in existing
            if rec.get("layer_name") != layer.get("name")
        }
        new_rec = recommend_layer(replacement_layer, layer_results or current_results, avoid_ids)
        if new_rec is None:
            raise ValueError("替换后的 Layer 暂时没有足够结果可推荐。")

        updated = self.recommendation_list_with_layer(db, session_id, updated_category, replacement_layer, new_rec)
        db.save_recommendations(session_id, category["id"], updated, "layer_recipe_changed")
        self.save_combo_snapshot(db, session_id, updated_category, "layer_recipe_changed", updated)
        return {
            "session_id": session_id,
            "select_category_id": category["id"],
            "message": f"{category['name']} / 第 {layer_index + 1} 层已替换为 {replacement_layer.get('name', 'Layer')}。",
        }


class HistoryDialog(QDialog):
    def __init__(self, sessions: list[dict[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("历史需求")
        self.resize(660, 430)
        self.selected_session_id: int | None = None

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        for session in sessions:
            item = QListWidgetItem(
                f"{session['updated_at']}  {session['title']}\n{session['requirement'][:90]}"
            )
            item.setData(Qt.UserRole, session["id"])
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        buttons = QHBoxLayout()
        open_button = QPushButton("打开")
        cancel_button = QPushButton("取消")
        buttons.addStretch(1)
        buttons.addWidget(open_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        open_button.clicked.connect(self.accept_selection)
        cancel_button.clicked.connect(self.reject)
        self.list_widget.itemDoubleClicked.connect(lambda _: self.accept_selection())

    def accept_selection(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_session_id = int(item.data(Qt.UserRole))
        self.accept()


class LocalRequirementDialog(QDialog):
    def __init__(
        self,
        config: LocalModelConfig,
        initial_requirement: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("模型拆解需求")
        self.resize(820, 720)

        layout = QVBoxLayout(self)

        self.requirement_edit = QTextEdit()
        self.requirement_edit.setPlaceholderText("输入这次要找的声音需求，例如：钓鱼游戏背包、购买、奖励、错误反馈等 UI 音效。")
        self.requirement_edit.setMinimumHeight(190)
        self.requirement_edit.setPlainText(initial_requirement)
        layout.addWidget(QLabel("本次需求"))
        layout.addWidget(self.requirement_edit)

        config_group = QGroupBox("模型路由")
        config_layout = QGridLayout(config_group)
        config_layout.setHorizontalSpacing(10)
        config_layout.setVerticalSpacing(8)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("自动：联网 GPT 优先，慢/断则本地", "auto")
        self.mode_combo.addItem("强制联网 GPT", "remote")
        self.mode_combo.addItem("强制本地模型", "local")
        mode_index = self.mode_combo.findData(config.mode)
        self.mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)

        self.remote_base_url_edit = QLineEdit(config.remote_base_url or DEFAULT_REMOTE_URL)
        self.remote_model_edit = QLineEdit(config.remote_model or DEFAULT_REMOTE_MODEL)
        self.remote_api_key_edit = QLineEdit(config.remote_api_key)
        self.remote_api_key_edit.setEchoMode(QLineEdit.Password)
        self.remote_slow_ms_edit = QLineEdit(str(config.remote_slow_ms))

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Ollama", "ollama")
        self.provider_combo.addItem("OpenAI-compatible / LM Studio", "openai_compatible")
        provider_index = self.provider_combo.findData(config.provider)
        self.provider_combo.setCurrentIndex(provider_index if provider_index >= 0 else 0)

        self.base_url_edit = QLineEdit(config.base_url)
        self.model_edit = QLineEdit(config.model)
        self.api_key_edit = QLineEdit(config.api_key)
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.temperature_edit = QLineEdit(str(config.temperature))
        self.timeout_edit = QLineEdit(str(config.timeout))
        self.max_categories_edit = QLineEdit(str(config.max_categories))
        self.auto_search_check = QCheckBox("拆解后直接搜索并生成推荐组合")
        self.auto_search_check.setChecked(True)
        self.fallback_check = QCheckBox("模型失败时使用内置规则继续")
        self.fallback_check.setChecked(config.allow_rule_fallback)

        config_layout.addWidget(QLabel("模式"), 0, 0)
        config_layout.addWidget(self.mode_combo, 0, 1)
        config_layout.addWidget(QLabel("远程 Base URL"), 1, 0)
        config_layout.addWidget(self.remote_base_url_edit, 1, 1)
        config_layout.addWidget(QLabel("远程 GPT 模型"), 2, 0)
        config_layout.addWidget(self.remote_model_edit, 2, 1)
        config_layout.addWidget(QLabel("远程 API Key"), 3, 0)
        config_layout.addWidget(self.remote_api_key_edit, 3, 1)
        config_layout.addWidget(QLabel("慢速阈值 ms"), 4, 0)
        config_layout.addWidget(self.remote_slow_ms_edit, 4, 1)
        config_layout.addWidget(QLabel("本地服务类型"), 5, 0)
        config_layout.addWidget(self.provider_combo, 5, 1)
        config_layout.addWidget(QLabel("本地 Base URL"), 6, 0)
        config_layout.addWidget(self.base_url_edit, 6, 1)
        config_layout.addWidget(QLabel("本地模型名"), 7, 0)
        config_layout.addWidget(self.model_edit, 7, 1)
        config_layout.addWidget(QLabel("本地 API Key"), 8, 0)
        config_layout.addWidget(self.api_key_edit, 8, 1)
        config_layout.addWidget(QLabel("Temperature"), 9, 0)
        config_layout.addWidget(self.temperature_edit, 9, 1)
        config_layout.addWidget(QLabel("Timeout 秒"), 10, 0)
        config_layout.addWidget(self.timeout_edit, 10, 1)
        config_layout.addWidget(QLabel("最多分类"), 11, 0)
        config_layout.addWidget(self.max_categories_edit, 11, 1)
        config_layout.addWidget(self.auto_search_check, 12, 1)
        config_layout.addWidget(self.fallback_check, 13, 1)
        layout.addWidget(config_group)

        help_text = QLabel(
            "自动模式会在每次请求前探测远程 GPT，通畅且不慢才使用联网模式；否则切到本地模型。"
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        buttons = QHBoxLayout()
        run_button = QPushButton("拆解并执行")
        cancel_button = QPushButton("取消")
        buttons.addStretch(1)
        buttons.addWidget(run_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self.provider_combo.currentIndexChanged.connect(self.provider_changed)
        run_button.clicked.connect(self.accept_selection)
        cancel_button.clicked.connect(self.reject)

    def provider_changed(self) -> None:
        provider = str(self.provider_combo.currentData())
        current_url = self.base_url_edit.text().strip()
        if provider == "ollama" and current_url in {"", DEFAULT_OPENAI_URL}:
            self.base_url_edit.setText(DEFAULT_OLLAMA_URL)
        elif provider == "openai_compatible" and current_url in {"", DEFAULT_OLLAMA_URL}:
            self.base_url_edit.setText(DEFAULT_OPENAI_URL)

    def requirement(self) -> str:
        return self.requirement_edit.toPlainText().strip()

    def selected_config(self) -> LocalModelConfig:
        return LocalModelConfig(
            mode=str(self.mode_combo.currentData()),
            provider=str(self.provider_combo.currentData()),
            base_url=self.base_url_edit.text().strip(),
            model=self.model_edit.text().strip(),
            api_key=self.api_key_edit.text().strip(),
            remote_base_url=self.remote_base_url_edit.text().strip(),
            remote_model=self.remote_model_edit.text().strip(),
            remote_api_key=self.remote_api_key_edit.text().strip(),
            remote_slow_ms=max(1, self.int_value(self.remote_slow_ms_edit.text(), 6000)),
            temperature=self.float_value(self.temperature_edit.text(), 0.2),
            timeout=self.int_value(self.timeout_edit.text(), 90),
            max_categories=max(1, self.int_value(self.max_categories_edit.text(), 10)),
            allow_rule_fallback=self.fallback_check.isChecked(),
        )

    def accept_selection(self) -> None:
        if not self.requirement():
            QMessageBox.information(self, "需要需求", "请先输入本次声音需求。")
            return
        config = self.selected_config()
        if config.mode in {"auto", "remote"} and not config.remote_base_url:
            QMessageBox.information(self, "需要远程 Base URL", "请填写远程 GPT 服务地址。")
            return
        if config.mode in {"auto", "remote"} and not config.remote_model:
            QMessageBox.information(self, "需要远程模型名", "请填写远程 GPT 模型名。")
            return
        if config.mode in {"auto", "local"} and not config.base_url:
            QMessageBox.information(self, "需要 Base URL", "请填写本地模型服务地址。")
            return
        if config.mode in {"auto", "local"} and not config.model:
            QMessageBox.information(self, "需要模型名", "请填写本地模型名。")
            return
        self.accept()

    @staticmethod
    def float_value(text: str, default: float) -> float:
        try:
            return float(text.strip())
        except ValueError:
            return default

    @staticmethod
    def int_value(text: str, default: int) -> int:
        try:
            return int(float(text.strip()))
        except ValueError:
            return default


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.db = SoundFinderDB()
        self.current_session_id: int | None = None
        self.current_results: list[dict[str, Any]] = []
        self.current_layer_index: int | None = None
        self.selected_result: dict[str, Any] | None = None
        self.session_switcher_blocked = False
        self.audio_analysis_cache: dict[str, dict[str, Any]] = {}
        self.pending_seek_position_ms: int | None = None
        self.pending_seek_path = ""

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.75)
        self.player.positionChanged.connect(self.player_position_changed)
        self.player.mediaStatusChanged.connect(self.player_media_status_changed)

        self.setWindowTitle("Sound Finder for Reaper")
        self.resize(1460, 900)
        self.build_ui_workbench()
        self.apply_style()
        self.restore_settings()
        self.refresh_audio_count()

    def build_ui_workbench(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.setCentralWidget(central)

        library_bar = QHBoxLayout()
        library_bar.setSpacing(8)
        self.library_path = QLineEdit()
        self.library_path.setReadOnly(True)
        self.library_path.setPlaceholderText("选择你的本地音效库根目录")
        choose_button = QPushButton("选择音效库")
        self.scan_button = QPushButton("增量扫描")
        self.rebuild_button = QPushButton("重建索引")
        clean_index_button = QPushButton("清理旧索引")
        refresh_sessions_button = QPushButton("刷新任务")
        self.audio_count_label = QLabel("索引：0")
        self.task_status_label = QLabel("后台任务空闲")
        self.task_status_label.setObjectName("statusChip")
        self.session_switcher = QComboBox()
        self.session_switcher.setMinimumWidth(330)
        library_bar.addWidget(QLabel("音效库"))
        library_bar.addWidget(self.library_path, 1)
        library_bar.addWidget(choose_button)
        library_bar.addWidget(self.scan_button)
        library_bar.addWidget(self.rebuild_button)
        library_bar.addWidget(clean_index_button)
        library_bar.addWidget(self.audio_count_label)
        library_bar.addWidget(self.task_status_label)
        library_bar.addWidget(QLabel("任务"))
        library_bar.addWidget(self.session_switcher)
        library_bar.addWidget(refresh_sessions_button)
        root.addLayout(library_bar)

        choose_button.clicked.connect(self.choose_library)
        self.scan_button.clicked.connect(self.scan_library)
        self.rebuild_button.clicked.connect(self.rebuild_index)
        clean_index_button.clicked.connect(self.clean_old_index)
        refresh_sessions_button.clicked.connect(self.refresh_session_switcher)
        self.session_switcher.currentIndexChanged.connect(self.session_switcher_changed)

        summary_group = QGroupBox("任务摘要")
        summary_outer = QVBoxLayout(summary_group)
        summary_outer.setContentsMargins(12, 8, 12, 8)
        summary_outer.setSpacing(6)
        self.task_summary_label = QLabel("未载入任务")
        self.task_summary_label.setWordWrap(True)
        self.task_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.toggle_plan_button = QPushButton("展开需求/方案")
        self.local_model_button = QPushButton("模型拆解/搜索")
        import_button = QPushButton("导入 Codex 方案")
        result_limit_label = QLabel("每栏条数")
        self.result_limit_spin = QSpinBox()
        self.result_limit_spin.setRange(1, 2000)
        self.result_limit_spin.setValue(self._saved_result_limit())
        self.result_limit_spin.setToolTip("每个分类显示并保存的结果条数（下次搜索时生效）")
        self.result_limit_spin.valueChanged.connect(self._on_result_limit_changed)
        self.search_button = QPushButton("确认并搜索")
        save_plan_button = QPushButton("保存方案")
        export_button = QPushButton("导出方案")
        add_row_button = QPushButton("添加分类")
        clear_button = QPushButton("清空当前需求")
        history_button = QPushButton("载入历史需求")
        reaper_tracks_button = QPushButton("REAPER Tracks")
        self.open_reaper_project_button = QPushButton("Open REAPER Project")
        self.open_reaper_project_button.setEnabled(False)
        soundly_button = QPushButton("Soundly Sheet")

        # Row 1: a collapse toggle + the requirement summary on its OWN full-width line
        # (previously it was squeezed between the buttons into a tall vertical sliver).
        self.toggle_summary_button = QToolButton()
        self.toggle_summary_button.setText("▾ 摘要")
        self.toggle_summary_button.setCheckable(True)
        self.toggle_summary_button.setChecked(True)
        self.toggle_summary_button.setToolTip("折叠/展开任务摘要文字")
        self.toggle_summary_button.toggled.connect(self._toggle_summary_text)
        summary_top_row = QHBoxLayout()
        summary_top_row.setSpacing(6)
        summary_top_row.addWidget(self.toggle_summary_button)
        summary_top_row.addWidget(self.task_summary_label, 1)
        summary_outer.addLayout(summary_top_row)

        # Row 2: all actions in their own row, so they never crush the summary text.
        button_row = QHBoxLayout()
        button_row.setSpacing(6)
        for widget in (
            self.toggle_plan_button,
            self.local_model_button,
            import_button,
            result_limit_label,
            self.result_limit_spin,
            self.search_button,
            save_plan_button,
            export_button,
            add_row_button,
            clear_button,
            reaper_tracks_button,
            self.open_reaper_project_button,
            soundly_button,
            history_button,
        ):
            button_row.addWidget(widget)
        button_row.addStretch(1)
        summary_outer.addLayout(button_row)
        root.addWidget(summary_group)

        self.toggle_plan_button.clicked.connect(self.toggle_plan_detail)
        self.local_model_button.clicked.connect(self.local_model_requirement)
        import_button.clicked.connect(self.import_codex_plan)
        self.search_button.clicked.connect(self.confirm_and_search)
        save_plan_button.clicked.connect(self.save_plan_only)
        export_button.clicked.connect(self.export_plan)
        add_row_button.clicked.connect(self.add_empty_category)
        clear_button.clicked.connect(self.clear_current)
        history_button.clicked.connect(self.load_history)
        reaper_tracks_button.clicked.connect(self.create_reaper_requirement_tracks)
        self.open_reaper_project_button.clicked.connect(self.open_current_reaper_project)
        soundly_button.clicked.connect(self.export_soundly_sheet)

        self.plan_detail_group = QGroupBox("需求/方案详情")
        plan_detail_layout = QVBoxLayout(self.plan_detail_group)
        plan_detail_layout.setContentsMargins(12, 14, 12, 12)
        self.requirement_edit = QTextEdit()
        self.requirement_edit.setPlaceholderText("Codex 导入的需求文本，通常折叠起来即可。")
        self.requirement_edit.setFixedHeight(58)
        plan_detail_layout.addWidget(self.requirement_edit)
        self.plan_table = QTableWidget(0, 5)
        self.plan_table.setHorizontalHeaderLabels(["搜索", "分类", "配方", "声音方向", "英文关键词"])
        self.plan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.verticalHeader().setDefaultSectionSize(30)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.plan_table.setFixedHeight(132)
        plan_detail_layout.addWidget(self.plan_table)
        self.plan_detail_group.setVisible(False)
        root.addWidget(self.plan_detail_group)

        workspace_splitter = QSplitter(Qt.Horizontal)
        root.addWidget(workspace_splitter, 1)
        left_splitter = QSplitter(Qt.Vertical)
        workspace_splitter.addWidget(left_splitter)
        result_splitter = QSplitter(Qt.Horizontal)
        left_splitter.addWidget(result_splitter)

        category_group = QGroupBox("分类")
        category_layout = QVBoxLayout(category_group)
        category_layout.setContentsMargins(10, 14, 10, 10)
        self.category_filter = QLineEdit()
        self.category_filter.setPlaceholderText("过滤分类")
        self.category_list = QListWidget()
        category_layout.addWidget(self.category_filter)
        category_layout.addWidget(self.category_list, 1)
        self.category_list.currentItemChanged.connect(self.category_changed)
        self.category_filter.textChanged.connect(lambda _: self.populate_categories())
        result_splitter.addWidget(category_group)

        search_group = QGroupBox("搜索结果")
        search_layout = QVBoxLayout(search_group)
        search_layout.setContentsMargins(10, 14, 10, 10)
        filter_row = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("过滤文件名、路径或匹配词")
        self.favorites_only = QCheckBox("只看收藏")
        self.used_only = QCheckBox("只看已用")
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.favorites_only)
        filter_row.addWidget(self.used_only)
        search_layout.addLayout(filter_row)

        self.result_table = ResultTable(0, 7)
        self.result_table.setHorizontalHeaderLabels(["分数", "文件名", "时长", "分类", "匹配关键词", "收藏", "已用"])
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.verticalHeader().setDefaultSectionSize(34)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.setDragEnabled(True)
        self.result_table.setDragDropMode(QAbstractItemView.DragOnly)
        search_layout.addWidget(self.result_table, 1)
        self.result_table.itemSelectionChanged.connect(self.result_selection_changed)
        self.result_table.itemClicked.connect(self.auto_play_selected_after_click)
        self.filter_edit.textChanged.connect(self.populate_result_table)
        self.favorites_only.stateChanged.connect(self.populate_result_table)
        self.used_only.stateChanged.connect(self.populate_result_table)
        result_splitter.addWidget(search_group)
        result_splitter.setSizes([280, 980])

        combo_group = QGroupBox("推荐组合 / Layer")
        combo_layout = QVBoxLayout(combo_group)
        combo_layout.setContentsMargins(10, 14, 10, 10)
        combo_splitter = QSplitter(Qt.Vertical)
        combo_layout.addWidget(combo_splitter, 1)

        layer_panel = QWidget()
        layer_layout = QVBoxLayout(layer_panel)
        layer_layout.setContentsMargins(0, 0, 0, 0)
        layer_layout.setSpacing(8)
        self.recipe_text = QPlainTextEdit()
        self.recipe_text.setReadOnly(True)
        self.recipe_text.setMinimumHeight(82)
        layer_layout.addWidget(self.recipe_text)
        self.layer_table = QTableWidget(0, 4)
        self.layer_table.setHorizontalHeaderLabels(["#", "Layer", "当前素材", "分数"])
        self.layer_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.layer_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.layer_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.layer_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.layer_table.verticalHeader().setVisible(False)
        self.layer_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.layer_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.layer_table.setAlternatingRowColors(True)
        self.layer_table.setMinimumHeight(140)
        layer_layout.addWidget(self.layer_table)
        self.layer_detail_text = QPlainTextEdit()
        self.layer_detail_text.setReadOnly(True)
        self.layer_detail_text.setMinimumHeight(68)
        layer_layout.addWidget(self.layer_detail_text)
        layer_actions = QGridLayout()
        layer_actions.setHorizontalSpacing(8)
        layer_actions.setVerticalSpacing(8)
        self.recommend_button = QPushButton("推荐组合")
        self.change_recipe_button = QPushButton("改配方")
        self.layer_search_button = QPushButton("重搜 Layer")
        self.layer_recipe_button = QPushButton("替换 Layer")
        self.similar_button = QPushButton("随机相似素材")
        layer_actions.addWidget(self.recommend_button, 0, 0)
        layer_actions.addWidget(self.change_recipe_button, 0, 1)
        layer_actions.addWidget(self.layer_search_button, 1, 0)
        layer_actions.addWidget(self.layer_recipe_button, 1, 1)
        layer_actions.addWidget(self.similar_button, 2, 0, 1, 2)
        layer_layout.addLayout(layer_actions)
        combo_splitter.addWidget(layer_panel)

        # Keep an internal recommendation table for existing selection/rebuild logic,
        # but do not show a duplicate "推荐素材" region in the right column.
        self.recommendation_table = QTableWidget(0, 4)
        self.recommendation_table.setHorizontalHeaderLabels(["Layer", "推荐素材", "分数", "原因"])
        self.recommendation_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.recommendation_table.verticalHeader().setVisible(False)
        self.recommendation_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.recommendation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recommendation_table.setVisible(False)

        history_panel = QWidget()
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(8)
        history_row = QHBoxLayout()
        restore_history_button = QPushButton("恢复组合")
        history_row.addWidget(QLabel("组合历史"))
        history_row.addStretch(1)
        history_row.addWidget(restore_history_button)
        history_layout.addLayout(history_row)
        self.combo_history_list = QListWidget()
        self.combo_history_list.setMinimumHeight(96)
        history_layout.addWidget(self.combo_history_list, 1)
        combo_splitter.addWidget(history_panel)
        combo_splitter.setSizes([560, 180])
        workspace_splitter.addWidget(combo_group)

        self.recommend_button.clicked.connect(self.recommend_current_category)
        self.change_recipe_button.clicked.connect(self.change_recipe)
        self.layer_search_button.clicked.connect(self.research_current_layer)
        self.layer_recipe_button.clicked.connect(self.replace_current_layer_recipe)
        self.similar_button.clicked.connect(self.random_similar_material)
        self.layer_table.itemSelectionChanged.connect(self.layer_selection_changed)
        self.recommendation_table.itemSelectionChanged.connect(self.recommendation_selection_changed)
        self.layer_table.itemClicked.connect(self.auto_play_selected_after_click)
        self.recommendation_table.itemClicked.connect(self.auto_play_selected_after_click)
        restore_history_button.clicked.connect(self.restore_selected_combo_history)
        self.combo_history_list.itemDoubleClicked.connect(lambda _: self.restore_selected_combo_history())

        audio_group = QGroupBox("当前选中音频 / 波形 / 参数")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setContentsMargins(12, 14, 12, 12)
        self.detail_name = QLabel("未选择文件")
        self.detail_name.setWordWrap(True)
        self.detail_meta = QLabel("")
        self.detail_meta.setWordWrap(True)
        audio_header = QHBoxLayout()
        audio_header.setSpacing(12)
        audio_info = QVBoxLayout()
        audio_info.addWidget(self.detail_name)
        audio_info.addWidget(self.detail_meta)
        audio_header.addLayout(audio_info, 1)
        audio_actions = QHBoxLayout()
        audio_actions.setSpacing(8)
        play_button = QToolButton()
        stop_button = QToolButton()
        favorite_button = QToolButton()
        used_button = QToolButton()
        open_button = QToolButton()
        copy_button = QToolButton()
        play_button.setText("播放")
        stop_button.setText("停止")
        favorite_button.setText("收藏")
        used_button.setText("已用")
        open_button.setText("位置")
        copy_button.setText("复制路径")
        audio_actions.addWidget(play_button)
        audio_actions.addWidget(stop_button)
        audio_actions.addWidget(favorite_button)
        audio_actions.addWidget(used_button)
        audio_actions.addWidget(open_button)
        audio_actions.addWidget(copy_button)
        audio_header.addLayout(audio_actions)
        self.audio_stats_label = QLabel("Ch: -    SR: -    Bit: -    Duration: -    Peak: -    RMS: -    LUFS-I≈: -")
        self.audio_stats_label.setWordWrap(True)
        self.waveform_placeholder = WaveformView()
        self.waveform_placeholder.seekRequested.connect(self.play_from_waveform_ratio)
        audio_layout.addLayout(audio_header)
        audio_layout.addWidget(self.waveform_placeholder)
        audio_layout.addWidget(self.audio_stats_label)
        detail_splitter = QSplitter(Qt.Horizontal)
        self.detail_path = QPlainTextEdit()
        self.detail_path.setReadOnly(True)
        self.detail_path.setFixedHeight(50)
        self.keyword_text = QPlainTextEdit()
        self.keyword_text.setReadOnly(True)
        self.keyword_text.setFixedHeight(50)
        detail_splitter.addWidget(self.detail_path)
        detail_splitter.addWidget(self.keyword_text)
        detail_splitter.setSizes([900, 420])
        audio_layout.addWidget(detail_splitter)
        self.drag_label = DragFileLabel("选择一个或多个结果后可拖拽到 Reaper")
        self.drag_label.setVisible(False)
        left_splitter.addWidget(audio_group)
        left_splitter.setSizes([660, 260])
        workspace_splitter.setSizes([1280, 600])

        play_button.clicked.connect(self.play_selected)
        stop_button.clicked.connect(self.player.stop)
        favorite_button.clicked.connect(self.toggle_favorite)
        used_button.clicked.connect(self.toggle_used)
        open_button.clicked.connect(self.open_selected_location)
        copy_button.clicked.connect(self.copy_selected_path)

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        self.menuBar().addMenu("文件").addAction(exit_action)
        self.statusBar().showMessage("准备就绪")

    def build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        self.setCentralWidget(central)

        library_bar = QHBoxLayout()
        self.library_path = QLineEdit()
        self.library_path.setReadOnly(True)
        self.library_path.setPlaceholderText("选择你的本地音效库根目录")
        choose_button = QPushButton("选择音效库")
        self.scan_button = QPushButton("增量扫描")
        self.rebuild_button = QPushButton("重建索引")
        clean_index_button = QPushButton("清理旧索引")
        self.audio_count_label = QLabel("索引：0")
        library_bar.addWidget(QLabel("音效库"))
        library_bar.addWidget(self.library_path, 1)
        library_bar.addWidget(choose_button)
        library_bar.addWidget(self.scan_button)
        library_bar.addWidget(self.rebuild_button)
        library_bar.addWidget(clean_index_button)
        library_bar.addWidget(self.audio_count_label)
        root.addLayout(library_bar)

        choose_button.clicked.connect(self.choose_library)
        self.scan_button.clicked.connect(self.scan_library)
        self.rebuild_button.clicked.connect(self.rebuild_index)
        clean_index_button.clicked.connect(self.clean_old_index)

        main_splitter = QSplitter(Qt.Vertical)
        root.addWidget(main_splitter, 1)

        requirement_group = QGroupBox("Codex 方案承接区")
        requirement_layout = QVBoxLayout(requirement_group)
        self.requirement_edit = QTextEdit()
        self.requirement_edit.setPlaceholderText(
            "这里放我在对话里整理并确认后的需求。工具只负责承接方案、搜索、推荐和保存。"
        )
        self.requirement_edit.setFixedHeight(74)
        requirement_layout.addWidget(self.requirement_edit)

        action_bar = QHBoxLayout()
        import_button = QPushButton("导入 Codex 方案")
        self.search_button = QPushButton("确认并搜索")
        save_plan_button = QPushButton("保存方案")
        export_button = QPushButton("导出方案")
        add_row_button = QPushButton("添加分类")
        clear_button = QPushButton("清空当前需求")
        history_button = QPushButton("载入历史需求")
        reaper_tracks_button = QPushButton("创建 REAPER 需求轨")
        action_bar.addWidget(import_button)
        action_bar.addWidget(self.search_button)
        action_bar.addWidget(save_plan_button)
        action_bar.addWidget(export_button)
        action_bar.addWidget(add_row_button)
        action_bar.addWidget(clear_button)
        action_bar.addWidget(reaper_tracks_button)
        action_bar.addStretch(1)
        action_bar.addWidget(history_button)
        requirement_layout.addLayout(action_bar)

        self.plan_table = QTableWidget(0, 5)
        self.plan_table.setHorizontalHeaderLabels(["搜索", "分类", "配方", "声音方向", "英文关键词"])
        self.plan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        requirement_layout.addWidget(self.plan_table, 1)

        import_button.clicked.connect(self.import_codex_plan)
        self.search_button.clicked.connect(self.confirm_and_search)
        save_plan_button.clicked.connect(self.save_plan_only)
        export_button.clicked.connect(self.export_plan)
        add_row_button.clicked.connect(self.add_empty_category)
        clear_button.clicked.connect(self.clear_current)
        history_button.clicked.connect(self.load_history)
        reaper_tracks_button.clicked.connect(self.create_reaper_requirement_tracks)

        main_splitter.addWidget(requirement_group)

        results_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(results_splitter)
        main_splitter.setSizes([330, 570])

        category_group = QGroupBox("需求分类")
        category_layout = QVBoxLayout(category_group)
        self.category_list = QListWidget()
        category_layout.addWidget(self.category_list)
        self.category_list.currentItemChanged.connect(self.category_changed)
        results_splitter.addWidget(category_group)

        results_group = QGroupBox("搜索结果")
        results_layout = QVBoxLayout(results_group)
        filter_row = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("过滤文件名、路径或匹配词")
        self.favorites_only = QCheckBox("只看收藏")
        self.used_only = QCheckBox("只看已用")
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.favorites_only)
        filter_row.addWidget(self.used_only)
        results_layout.addLayout(filter_row)

        self.result_table = ResultTable(0, 7)
        self.result_table.setHorizontalHeaderLabels(
            ["分数", "文件", "时长", "分类", "匹配词", "收藏", "已用"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.setDragEnabled(True)
        self.result_table.setDragDropMode(QAbstractItemView.DragOnly)
        results_layout.addWidget(self.result_table, 1)

        self.result_table.itemSelectionChanged.connect(self.result_selection_changed)
        self.result_table.itemClicked.connect(self.auto_play_selected_after_click)
        self.filter_edit.textChanged.connect(self.populate_result_table)
        self.favorites_only.stateChanged.connect(self.populate_result_table)
        self.used_only.stateChanged.connect(self.populate_result_table)
        results_splitter.addWidget(results_group)

        detail_group = QGroupBox("推荐 / 预览 / 拖拽")
        detail_layout = QVBoxLayout(detail_group)

        recommend_bar = QHBoxLayout()
        self.recommend_button = QPushButton("推荐组合")
        self.change_recipe_button = QPushButton("改变配方")
        self.layer_search_button = QPushButton("重搜当前 Layer")
        self.layer_recipe_button = QPushButton("替换当前 Layer")
        self.similar_button = QPushButton("随机相似素材")
        recommend_bar.addWidget(self.recommend_button)
        recommend_bar.addWidget(self.change_recipe_button)
        recommend_bar.addWidget(self.layer_search_button)
        recommend_bar.addWidget(self.layer_recipe_button)
        recommend_bar.addWidget(self.similar_button)
        detail_layout.addLayout(recommend_bar)

        self.recipe_text = QPlainTextEdit()
        self.recipe_text.setReadOnly(True)
        self.recipe_text.setFixedHeight(86)
        detail_layout.addWidget(QLabel("当前配方"))
        detail_layout.addWidget(self.recipe_text)

        self.layer_table = QTableWidget(0, 4)
        self.layer_table.setHorizontalHeaderLabels(["#", "Layer", "当前素材", "分数"])
        self.layer_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.layer_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.layer_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.layer_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.layer_table.verticalHeader().setVisible(False)
        self.layer_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.layer_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.layer_table.setAlternatingRowColors(True)
        self.layer_table.setFixedHeight(136)
        detail_layout.addWidget(QLabel("配方 Layer"))
        detail_layout.addWidget(self.layer_table)

        self.layer_detail_text = QPlainTextEdit()
        self.layer_detail_text.setReadOnly(True)
        self.layer_detail_text.setFixedHeight(64)
        detail_layout.addWidget(self.layer_detail_text)

        self.recommendation_table = QTableWidget(0, 4)
        self.recommendation_table.setHorizontalHeaderLabels(["Layer", "推荐素材", "分数", "原因"])
        self.recommendation_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.recommendation_table.verticalHeader().setVisible(False)
        self.recommendation_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.recommendation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        detail_layout.addWidget(self.recommendation_table)

        history_row = QHBoxLayout()
        restore_history_button = QPushButton("恢复组合")
        history_row.addWidget(QLabel("组合历史"))
        history_row.addStretch(1)
        history_row.addWidget(restore_history_button)
        detail_layout.addLayout(history_row)
        self.combo_history_list = QListWidget()
        self.combo_history_list.setFixedHeight(96)
        detail_layout.addWidget(self.combo_history_list)

        self.detail_name = QLabel("未选择文件")
        self.detail_name.setWordWrap(True)
        self.detail_path = QPlainTextEdit()
        self.detail_path.setReadOnly(True)
        self.detail_path.setFixedHeight(62)
        self.detail_meta = QLabel("")
        self.detail_meta.setWordWrap(True)
        self.keyword_text = QPlainTextEdit()
        self.keyword_text.setReadOnly(True)
        self.keyword_text.setFixedHeight(72)
        detail_layout.addWidget(self.detail_name)
        detail_layout.addWidget(self.detail_meta)
        detail_layout.addWidget(QLabel("路径"))
        detail_layout.addWidget(self.detail_path)
        detail_layout.addWidget(QLabel("匹配关键词"))
        detail_layout.addWidget(self.keyword_text)

        preview_buttons = QGridLayout()
        play_button = QToolButton()
        stop_button = QToolButton()
        favorite_button = QToolButton()
        used_button = QToolButton()
        open_button = QToolButton()
        copy_button = QToolButton()
        play_button.setText("播放")
        stop_button.setText("停止")
        favorite_button.setText("收藏")
        used_button.setText("已用")
        open_button.setText("位置")
        copy_button.setText("复制路径")
        preview_buttons.addWidget(play_button, 0, 0)
        preview_buttons.addWidget(stop_button, 0, 1)
        preview_buttons.addWidget(favorite_button, 0, 2)
        preview_buttons.addWidget(used_button, 1, 0)
        preview_buttons.addWidget(open_button, 1, 1)
        preview_buttons.addWidget(copy_button, 1, 2)
        detail_layout.addLayout(preview_buttons)

        self.drag_label = DragFileLabel("选择一个结果后可拖拽到 Reaper")
        detail_layout.addWidget(self.drag_label)

        self.recommend_button.clicked.connect(self.recommend_current_category)
        self.change_recipe_button.clicked.connect(self.change_recipe)
        self.layer_search_button.clicked.connect(self.research_current_layer)
        self.layer_recipe_button.clicked.connect(self.replace_current_layer_recipe)
        self.similar_button.clicked.connect(self.random_similar_material)
        self.layer_table.itemSelectionChanged.connect(self.layer_selection_changed)
        self.recommendation_table.itemSelectionChanged.connect(self.recommendation_selection_changed)
        self.layer_table.itemClicked.connect(self.auto_play_selected_after_click)
        self.recommendation_table.itemClicked.connect(self.auto_play_selected_after_click)
        restore_history_button.clicked.connect(self.restore_selected_combo_history)
        self.combo_history_list.itemDoubleClicked.connect(lambda _: self.restore_selected_combo_history())
        play_button.clicked.connect(self.play_selected)
        stop_button.clicked.connect(self.player.stop)
        favorite_button.clicked.connect(self.toggle_favorite)
        used_button.clicked.connect(self.toggle_used)
        open_button.clicked.connect(self.open_selected_location)
        copy_button.clicked.connect(self.copy_selected_path)
        results_splitter.addWidget(detail_group)
        results_splitter.setSizes([250, 720, 490])

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        self.menuBar().addMenu("文件").addAction(exit_action)
        self.statusBar().showMessage("准备就绪")

    def build_ui_paged(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.setCentralWidget(central)

        library_bar = QHBoxLayout()
        library_bar.setSpacing(8)
        self.library_path = QLineEdit()
        self.library_path.setReadOnly(True)
        self.library_path.setPlaceholderText("选择你的本地音效库根目录")
        choose_button = QPushButton("选择音效库")
        self.scan_button = QPushButton("增量扫描")
        self.rebuild_button = QPushButton("重建索引")
        clean_index_button = QPushButton("清理旧索引")
        refresh_sessions_button = QPushButton("刷新任务")
        self.audio_count_label = QLabel("索引：0")
        self.task_status_label = QLabel("后台任务空闲")
        self.task_status_label.setObjectName("statusChip")
        self.session_switcher = QComboBox()
        self.session_switcher.setMinimumWidth(300)
        library_bar.addWidget(QLabel("音效库"))
        library_bar.addWidget(self.library_path, 1)
        library_bar.addWidget(choose_button)
        library_bar.addWidget(self.scan_button)
        library_bar.addWidget(self.rebuild_button)
        library_bar.addWidget(clean_index_button)
        library_bar.addWidget(self.audio_count_label)
        library_bar.addWidget(self.task_status_label)
        library_bar.addWidget(QLabel("任务"))
        library_bar.addWidget(self.session_switcher)
        library_bar.addWidget(refresh_sessions_button)
        root.addLayout(library_bar)

        choose_button.clicked.connect(self.choose_library)
        self.scan_button.clicked.connect(self.scan_library)
        self.rebuild_button.clicked.connect(self.rebuild_index)
        clean_index_button.clicked.connect(self.clean_old_index)
        refresh_sessions_button.clicked.connect(self.refresh_session_switcher)
        self.session_switcher.currentIndexChanged.connect(self.session_switcher_changed)

        self.main_tabs = QTabWidget()
        root.addWidget(self.main_tabs, 1)

        plan_page = QWidget()
        plan_layout = QVBoxLayout(plan_page)
        plan_layout.setContentsMargins(12, 12, 12, 12)
        plan_layout.setSpacing(10)

        requirement_group = QGroupBox("需求与方案")
        requirement_layout = QVBoxLayout(requirement_group)
        requirement_layout.setContentsMargins(12, 14, 12, 12)
        requirement_layout.setSpacing(10)
        self.requirement_edit = QTextEdit()
        self.requirement_edit.setPlaceholderText(
            "这里放我在对话里整理并确认后的需求。确认后进入结果页做搜索、预览和 Layer 组合。"
        )
        self.requirement_edit.setMinimumHeight(150)
        requirement_layout.addWidget(self.requirement_edit)

        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)
        import_button = QPushButton("导入 Codex 方案")
        self.search_button = QPushButton("确认并搜索")
        save_plan_button = QPushButton("保存方案")
        export_button = QPushButton("导出方案")
        add_row_button = QPushButton("添加分类")
        clear_button = QPushButton("清空当前需求")
        history_button = QPushButton("载入历史需求")
        go_result_button = QPushButton("进入结果页")
        action_bar.addWidget(import_button)
        action_bar.addWidget(self.search_button)
        action_bar.addWidget(save_plan_button)
        action_bar.addWidget(export_button)
        action_bar.addWidget(add_row_button)
        action_bar.addWidget(clear_button)
        action_bar.addStretch(1)
        action_bar.addWidget(history_button)
        action_bar.addWidget(go_result_button)
        requirement_layout.addLayout(action_bar)
        plan_layout.addWidget(requirement_group)

        plan_group = QGroupBox("需求分类与关键词")
        plan_table_layout = QVBoxLayout(plan_group)
        plan_table_layout.setContentsMargins(12, 14, 12, 12)
        self.plan_table = QTableWidget(0, 5)
        self.plan_table.setHorizontalHeaderLabels(["搜索", "分类", "配方", "声音方向", "英文关键词"])
        self.plan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.verticalHeader().setDefaultSectionSize(34)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        plan_table_layout.addWidget(self.plan_table)
        plan_layout.addWidget(plan_group, 1)

        import_button.clicked.connect(self.import_codex_plan)
        self.search_button.clicked.connect(self.confirm_and_search)
        save_plan_button.clicked.connect(self.save_plan_only)
        export_button.clicked.connect(self.export_plan)
        add_row_button.clicked.connect(self.add_empty_category)
        clear_button.clicked.connect(self.clear_current)
        history_button.clicked.connect(self.load_history)
        go_result_button.clicked.connect(lambda: self.main_tabs.setCurrentIndex(1))

        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.setContentsMargins(12, 12, 12, 12)
        results_layout.setSpacing(8)
        result_nav = QHBoxLayout()
        back_plan_button = QPushButton("返回方案页")
        result_nav.addWidget(back_plan_button)
        result_nav.addStretch(1)
        result_nav.addWidget(QLabel("结果页：选择分类、筛选素材、调整 Layer、预览并拖拽到 Reaper"))
        results_layout.addLayout(result_nav)
        back_plan_button.clicked.connect(lambda: self.main_tabs.setCurrentIndex(0))

        workspace_splitter = QSplitter(Qt.Horizontal)
        results_layout.addWidget(workspace_splitter, 1)

        category_group = QGroupBox("需求分类")
        category_layout = QVBoxLayout(category_group)
        category_layout.setContentsMargins(10, 14, 10, 10)
        category_layout.setSpacing(8)
        self.category_filter = QLineEdit()
        self.category_filter.setPlaceholderText("过滤分类")
        self.category_list = QListWidget()
        category_layout.addWidget(self.category_filter)
        category_layout.addWidget(self.category_list, 1)
        self.category_list.currentItemChanged.connect(self.category_changed)
        self.category_filter.textChanged.connect(lambda _: self.populate_categories())
        workspace_splitter.addWidget(category_group)

        search_group = QGroupBox("搜索结果")
        search_layout = QVBoxLayout(search_group)
        search_layout.setContentsMargins(10, 14, 10, 10)
        search_layout.setSpacing(8)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("过滤文件名、路径或匹配词")
        self.favorites_only = QCheckBox("只看收藏")
        self.used_only = QCheckBox("只看已用")
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.favorites_only)
        filter_row.addWidget(self.used_only)
        search_layout.addLayout(filter_row)

        self.result_table = ResultTable(0, 7)
        self.result_table.setHorizontalHeaderLabels(
            ["分数", "文件名", "时长", "分类", "匹配关键词", "收藏", "已用"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.verticalHeader().setDefaultSectionSize(36)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.setDragEnabled(True)
        self.result_table.setDragDropMode(QAbstractItemView.DragOnly)
        search_layout.addWidget(self.result_table, 1)
        self.result_table.itemSelectionChanged.connect(self.result_selection_changed)
        self.result_table.itemClicked.connect(self.auto_play_selected_after_click)
        self.filter_edit.textChanged.connect(self.populate_result_table)
        self.favorites_only.stateChanged.connect(self.populate_result_table)
        self.used_only.stateChanged.connect(self.populate_result_table)
        workspace_splitter.addWidget(search_group)

        right_splitter = QSplitter(Qt.Vertical)

        layer_group = QGroupBox("配方 Layer")
        layer_layout = QVBoxLayout(layer_group)
        layer_layout.setContentsMargins(10, 14, 10, 10)
        layer_layout.setSpacing(8)
        self.recipe_text = QPlainTextEdit()
        self.recipe_text.setReadOnly(True)
        self.recipe_text.setFixedHeight(62)
        layer_layout.addWidget(self.recipe_text)
        self.layer_table = QTableWidget(0, 4)
        self.layer_table.setHorizontalHeaderLabels(["#", "Layer", "当前素材", "分数"])
        self.layer_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.layer_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.layer_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.layer_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.layer_table.verticalHeader().setVisible(False)
        self.layer_table.verticalHeader().setDefaultSectionSize(30)
        self.layer_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.layer_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.layer_table.setAlternatingRowColors(True)
        self.layer_table.setFixedHeight(136)
        layer_layout.addWidget(self.layer_table)
        self.layer_detail_text = QPlainTextEdit()
        self.layer_detail_text.setReadOnly(True)
        self.layer_detail_text.setFixedHeight(56)
        layer_layout.addWidget(self.layer_detail_text)
        layer_actions = QGridLayout()
        layer_actions.setHorizontalSpacing(8)
        layer_actions.setVerticalSpacing(8)
        self.recommend_button = QPushButton("推荐组合")
        self.change_recipe_button = QPushButton("改变配方")
        self.layer_search_button = QPushButton("重搜当前 Layer")
        self.layer_recipe_button = QPushButton("替换当前 Layer")
        self.similar_button = QPushButton("随机相似素材")
        layer_actions.addWidget(self.recommend_button, 0, 0)
        layer_actions.addWidget(self.change_recipe_button, 0, 1)
        layer_actions.addWidget(self.layer_search_button, 1, 0)
        layer_actions.addWidget(self.layer_recipe_button, 1, 1)
        layer_actions.addWidget(self.similar_button, 2, 0, 1, 2)
        layer_layout.addLayout(layer_actions)
        right_splitter.addWidget(layer_group)

        preview_group = QGroupBox("预览 / 拖拽")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(10, 14, 10, 10)
        preview_layout.setSpacing(8)
        self.detail_name = QLabel("未选择文件")
        self.detail_name.setWordWrap(True)
        self.detail_meta = QLabel("")
        self.detail_meta.setWordWrap(True)
        self.waveform_placeholder = QLabel("Waveform / Preview")
        self.waveform_placeholder.setObjectName("waveformBox")
        self.waveform_placeholder.setAlignment(Qt.AlignCenter)
        self.waveform_placeholder.setFixedHeight(48)
        preview_layout.addWidget(self.detail_name)
        preview_layout.addWidget(self.detail_meta)
        preview_layout.addWidget(self.waveform_placeholder)
        preview_buttons = QGridLayout()
        play_button = QToolButton()
        stop_button = QToolButton()
        favorite_button = QToolButton()
        used_button = QToolButton()
        open_button = QToolButton()
        copy_button = QToolButton()
        play_button.setText("播放")
        stop_button.setText("停止")
        favorite_button.setText("收藏")
        used_button.setText("已用")
        open_button.setText("位置")
        copy_button.setText("复制路径")
        preview_buttons.addWidget(play_button, 0, 0)
        preview_buttons.addWidget(stop_button, 0, 1)
        preview_buttons.addWidget(favorite_button, 0, 2)
        preview_buttons.addWidget(used_button, 1, 0)
        preview_buttons.addWidget(open_button, 1, 1)
        preview_buttons.addWidget(copy_button, 1, 2)
        preview_layout.addLayout(preview_buttons)
        self.detail_path = QPlainTextEdit()
        self.detail_path.setReadOnly(True)
        self.detail_path.setFixedHeight(44)
        self.keyword_text = QPlainTextEdit()
        self.keyword_text.setReadOnly(True)
        self.keyword_text.setFixedHeight(48)
        preview_layout.addWidget(QLabel("路径"))
        preview_layout.addWidget(self.detail_path)
        preview_layout.addWidget(QLabel("匹配关键词"))
        preview_layout.addWidget(self.keyword_text)
        self.drag_label = DragFileLabel("选择一个结果后可拖拽到 Reaper")
        preview_layout.addWidget(self.drag_label)
        right_splitter.addWidget(preview_group)

        combo_group = QGroupBox("推荐组合 / 组合历史")
        combo_layout = QVBoxLayout(combo_group)
        combo_layout.setContentsMargins(10, 14, 10, 10)
        combo_layout.setSpacing(8)
        self.recommendation_table = QTableWidget(0, 4)
        self.recommendation_table.setHorizontalHeaderLabels(["Layer", "推荐素材", "分数", "原因"])
        self.recommendation_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.recommendation_table.verticalHeader().setVisible(False)
        self.recommendation_table.verticalHeader().setDefaultSectionSize(30)
        self.recommendation_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.recommendation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        combo_layout.addWidget(self.recommendation_table, 1)
        history_row = QHBoxLayout()
        restore_history_button = QPushButton("恢复组合")
        history_row.addWidget(QLabel("组合历史"))
        history_row.addStretch(1)
        history_row.addWidget(restore_history_button)
        combo_layout.addLayout(history_row)
        self.combo_history_list = QListWidget()
        self.combo_history_list.setFixedHeight(78)
        combo_layout.addWidget(self.combo_history_list)
        right_splitter.addWidget(combo_group)
        right_splitter.setSizes([310, 290, 170])
        workspace_splitter.addWidget(right_splitter)
        workspace_splitter.setSizes([260, 900, 520])

        self.recommend_button.clicked.connect(self.recommend_current_category)
        self.change_recipe_button.clicked.connect(self.change_recipe)
        self.layer_search_button.clicked.connect(self.research_current_layer)
        self.layer_recipe_button.clicked.connect(self.replace_current_layer_recipe)
        self.similar_button.clicked.connect(self.random_similar_material)
        self.layer_table.itemSelectionChanged.connect(self.layer_selection_changed)
        self.recommendation_table.itemSelectionChanged.connect(self.recommendation_selection_changed)
        self.layer_table.itemClicked.connect(self.auto_play_selected_after_click)
        self.recommendation_table.itemClicked.connect(self.auto_play_selected_after_click)
        restore_history_button.clicked.connect(self.restore_selected_combo_history)
        self.combo_history_list.itemDoubleClicked.connect(lambda _: self.restore_selected_combo_history())
        play_button.clicked.connect(self.play_selected)
        stop_button.clicked.connect(self.player.stop)
        favorite_button.clicked.connect(self.toggle_favorite)
        used_button.clicked.connect(self.toggle_used)
        open_button.clicked.connect(self.open_selected_location)
        copy_button.clicked.connect(self.copy_selected_path)

        self.main_tabs.addTab(plan_page, "1 方案 / 需求")
        self.main_tabs.addTab(results_page, "2 结果 / Layer")

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        self.menuBar().addMenu("文件").addAction(exit_action)
        self.statusBar().showMessage("准备就绪")

    def build_ui_v2(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.setCentralWidget(central)

        library_bar = QHBoxLayout()
        library_bar.setSpacing(8)
        self.library_path = QLineEdit()
        self.library_path.setReadOnly(True)
        self.library_path.setPlaceholderText("选择你的本地音效库根目录")
        choose_button = QPushButton("选择音效库")
        self.scan_button = QPushButton("增量扫描")
        self.rebuild_button = QPushButton("重建索引")
        clean_index_button = QPushButton("清理旧索引")
        self.audio_count_label = QLabel("索引：0")
        self.task_status_label = QLabel("后台任务空闲")
        self.task_status_label.setObjectName("statusChip")
        library_bar.addWidget(QLabel("音效库"))
        library_bar.addWidget(self.library_path, 1)
        library_bar.addWidget(choose_button)
        library_bar.addWidget(self.scan_button)
        library_bar.addWidget(self.rebuild_button)
        library_bar.addWidget(clean_index_button)
        library_bar.addWidget(self.audio_count_label)
        library_bar.addWidget(self.task_status_label)
        root.addLayout(library_bar)

        choose_button.clicked.connect(self.choose_library)
        self.scan_button.clicked.connect(self.scan_library)
        self.rebuild_button.clicked.connect(self.rebuild_index)
        clean_index_button.clicked.connect(self.clean_old_index)

        requirement_group = QGroupBox("Codex 方案")
        requirement_layout = QVBoxLayout(requirement_group)
        requirement_layout.setContentsMargins(10, 12, 10, 10)
        requirement_layout.setSpacing(8)

        top_plan_row = QHBoxLayout()
        top_plan_row.setSpacing(10)
        self.requirement_edit = QTextEdit()
        self.requirement_edit.setPlaceholderText(
            "这里放我在对话里整理并确认后的需求。工具只负责承接方案、搜索、推荐和保存。"
        )
        self.requirement_edit.setFixedHeight(58)
        top_plan_row.addWidget(self.requirement_edit, 1)

        action_stack = QVBoxLayout()
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)
        import_button = QPushButton("导入 Codex 方案")
        self.search_button = QPushButton("确认并搜索")
        save_plan_button = QPushButton("保存方案")
        export_button = QPushButton("导出方案")
        add_row_button = QPushButton("添加分类")
        clear_button = QPushButton("清空当前需求")
        history_button = QPushButton("载入历史需求")
        action_bar.addWidget(import_button)
        action_bar.addWidget(self.search_button)
        action_bar.addWidget(save_plan_button)
        action_bar.addWidget(export_button)
        action_bar.addWidget(add_row_button)
        action_bar.addWidget(clear_button)
        action_bar.addStretch(1)
        action_bar.addWidget(history_button)
        action_stack.addLayout(action_bar)
        action_stack.addStretch(1)
        top_plan_row.addLayout(action_stack, 2)
        requirement_layout.addLayout(top_plan_row)

        self.plan_table = QTableWidget(0, 5)
        self.plan_table.setHorizontalHeaderLabels(["搜索", "分类", "配方", "声音方向", "英文关键词"])
        self.plan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.plan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.plan_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.verticalHeader().setDefaultSectionSize(30)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.plan_table.setFixedHeight(108)
        requirement_layout.addWidget(self.plan_table)
        root.addWidget(requirement_group)

        import_button.clicked.connect(self.import_codex_plan)
        self.search_button.clicked.connect(self.confirm_and_search)
        save_plan_button.clicked.connect(self.save_plan_only)
        export_button.clicked.connect(self.export_plan)
        add_row_button.clicked.connect(self.add_empty_category)
        clear_button.clicked.connect(self.clear_current)
        history_button.clicked.connect(self.load_history)

        workspace_splitter = QSplitter(Qt.Horizontal)
        root.addWidget(workspace_splitter, 1)

        category_group = QGroupBox("需求分类")
        category_layout = QVBoxLayout(category_group)
        category_layout.setContentsMargins(10, 12, 10, 10)
        category_layout.setSpacing(8)
        self.category_filter = QLineEdit()
        self.category_filter.setPlaceholderText("过滤分类")
        self.category_list = QListWidget()
        category_layout.addWidget(self.category_filter)
        category_layout.addWidget(self.category_list, 1)
        self.category_list.currentItemChanged.connect(self.category_changed)
        self.category_filter.textChanged.connect(lambda _: self.populate_categories())
        workspace_splitter.addWidget(category_group)

        results_group = QGroupBox("搜索结果")
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(10, 12, 10, 10)
        results_layout.setSpacing(8)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("过滤文件名、路径或匹配词")
        self.favorites_only = QCheckBox("只看收藏")
        self.used_only = QCheckBox("只看已用")
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.favorites_only)
        filter_row.addWidget(self.used_only)
        results_layout.addLayout(filter_row)

        self.result_table = ResultTable(0, 7)
        self.result_table.setHorizontalHeaderLabels(
            ["分数", "文件名", "时长", "分类", "匹配关键词", "收藏", "已用"]
        )
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.verticalHeader().setDefaultSectionSize(34)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.setDragEnabled(True)
        self.result_table.setDragDropMode(QAbstractItemView.DragOnly)
        results_layout.addWidget(self.result_table, 1)

        self.result_table.itemSelectionChanged.connect(self.result_selection_changed)
        self.result_table.itemClicked.connect(self.auto_play_selected_after_click)
        self.filter_edit.textChanged.connect(self.populate_result_table)
        self.favorites_only.stateChanged.connect(self.populate_result_table)
        self.used_only.stateChanged.connect(self.populate_result_table)
        workspace_splitter.addWidget(results_group)

        right_splitter = QSplitter(Qt.Vertical)

        layer_group = QGroupBox("配方 Layer")
        layer_layout = QVBoxLayout(layer_group)
        layer_layout.setContentsMargins(10, 12, 10, 10)
        layer_layout.setSpacing(8)
        self.recipe_text = QPlainTextEdit()
        self.recipe_text.setReadOnly(True)
        self.recipe_text.setFixedHeight(72)
        layer_layout.addWidget(self.recipe_text)

        self.layer_table = QTableWidget(0, 4)
        self.layer_table.setHorizontalHeaderLabels(["#", "Layer", "当前素材", "分数"])
        self.layer_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.layer_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.layer_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.layer_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.layer_table.verticalHeader().setVisible(False)
        self.layer_table.verticalHeader().setDefaultSectionSize(32)
        self.layer_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.layer_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.layer_table.setAlternatingRowColors(True)
        self.layer_table.setFixedHeight(152)
        layer_layout.addWidget(self.layer_table)

        self.layer_detail_text = QPlainTextEdit()
        self.layer_detail_text.setReadOnly(True)
        self.layer_detail_text.setFixedHeight(66)
        layer_layout.addWidget(self.layer_detail_text)

        layer_actions = QGridLayout()
        layer_actions.setHorizontalSpacing(8)
        layer_actions.setVerticalSpacing(8)
        self.recommend_button = QPushButton("推荐组合")
        self.change_recipe_button = QPushButton("改变配方")
        self.layer_search_button = QPushButton("重搜当前 Layer")
        self.layer_recipe_button = QPushButton("替换当前 Layer")
        self.similar_button = QPushButton("随机相似素材")
        layer_actions.addWidget(self.recommend_button, 0, 0)
        layer_actions.addWidget(self.change_recipe_button, 0, 1)
        layer_actions.addWidget(self.layer_search_button, 1, 0)
        layer_actions.addWidget(self.layer_recipe_button, 1, 1)
        layer_actions.addWidget(self.similar_button, 2, 0, 1, 2)
        layer_layout.addLayout(layer_actions)
        right_splitter.addWidget(layer_group)

        preview_group = QGroupBox("预览")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(10, 12, 10, 10)
        preview_layout.setSpacing(8)
        self.detail_name = QLabel("未选择文件")
        self.detail_name.setWordWrap(True)
        self.detail_meta = QLabel("")
        self.detail_meta.setWordWrap(True)
        self.waveform_placeholder = QLabel("Waveform / Preview")
        self.waveform_placeholder.setObjectName("waveformBox")
        self.waveform_placeholder.setAlignment(Qt.AlignCenter)
        self.waveform_placeholder.setFixedHeight(58)
        preview_layout.addWidget(self.detail_name)
        preview_layout.addWidget(self.detail_meta)
        preview_layout.addWidget(self.waveform_placeholder)

        preview_buttons = QGridLayout()
        preview_buttons.setHorizontalSpacing(8)
        preview_buttons.setVerticalSpacing(8)
        play_button = QToolButton()
        stop_button = QToolButton()
        favorite_button = QToolButton()
        used_button = QToolButton()
        open_button = QToolButton()
        copy_button = QToolButton()
        play_button.setText("播放")
        stop_button.setText("停止")
        favorite_button.setText("收藏")
        used_button.setText("已用")
        open_button.setText("位置")
        copy_button.setText("复制路径")
        preview_buttons.addWidget(play_button, 0, 0)
        preview_buttons.addWidget(stop_button, 0, 1)
        preview_buttons.addWidget(favorite_button, 0, 2)
        preview_buttons.addWidget(used_button, 1, 0)
        preview_buttons.addWidget(open_button, 1, 1)
        preview_buttons.addWidget(copy_button, 1, 2)
        preview_layout.addLayout(preview_buttons)

        self.detail_path = QPlainTextEdit()
        self.detail_path.setReadOnly(True)
        self.detail_path.setFixedHeight(52)
        self.keyword_text = QPlainTextEdit()
        self.keyword_text.setReadOnly(True)
        self.keyword_text.setFixedHeight(58)
        preview_layout.addWidget(QLabel("路径"))
        preview_layout.addWidget(self.detail_path)
        preview_layout.addWidget(QLabel("匹配关键词"))
        preview_layout.addWidget(self.keyword_text)
        self.drag_label = DragFileLabel("选择一个结果后可拖拽到 Reaper")
        preview_layout.addWidget(self.drag_label)
        right_splitter.addWidget(preview_group)

        combo_group = QGroupBox("推荐组合 / 组合历史")
        combo_layout = QVBoxLayout(combo_group)
        combo_layout.setContentsMargins(10, 12, 10, 10)
        combo_layout.setSpacing(8)
        self.recommendation_table = QTableWidget(0, 4)
        self.recommendation_table.setHorizontalHeaderLabels(["Layer", "推荐素材", "分数", "原因"])
        self.recommendation_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.recommendation_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.recommendation_table.verticalHeader().setVisible(False)
        self.recommendation_table.verticalHeader().setDefaultSectionSize(30)
        self.recommendation_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.recommendation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        combo_layout.addWidget(self.recommendation_table, 1)

        history_row = QHBoxLayout()
        restore_history_button = QPushButton("恢复组合")
        history_row.addWidget(QLabel("组合历史"))
        history_row.addStretch(1)
        history_row.addWidget(restore_history_button)
        combo_layout.addLayout(history_row)
        self.combo_history_list = QListWidget()
        self.combo_history_list.setFixedHeight(104)
        combo_layout.addWidget(self.combo_history_list)
        right_splitter.addWidget(combo_group)
        right_splitter.setSizes([320, 300, 260])
        workspace_splitter.addWidget(right_splitter)
        workspace_splitter.setSizes([260, 850, 470])

        self.recommend_button.clicked.connect(self.recommend_current_category)
        self.change_recipe_button.clicked.connect(self.change_recipe)
        self.layer_search_button.clicked.connect(self.research_current_layer)
        self.layer_recipe_button.clicked.connect(self.replace_current_layer_recipe)
        self.similar_button.clicked.connect(self.random_similar_material)
        self.layer_table.itemSelectionChanged.connect(self.layer_selection_changed)
        self.recommendation_table.itemSelectionChanged.connect(self.recommendation_selection_changed)
        self.layer_table.itemClicked.connect(self.auto_play_selected_after_click)
        self.recommendation_table.itemClicked.connect(self.auto_play_selected_after_click)
        restore_history_button.clicked.connect(self.restore_selected_combo_history)
        self.combo_history_list.itemDoubleClicked.connect(lambda _: self.restore_selected_combo_history())
        play_button.clicked.connect(self.play_selected)
        stop_button.clicked.connect(self.player.stop)
        favorite_button.clicked.connect(self.toggle_favorite)
        used_button.clicked.connect(self.toggle_used)
        open_button.clicked.connect(self.open_selected_location)
        copy_button.clicked.connect(self.copy_selected_path)

        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        self.menuBar().addMenu("文件").addAction(exit_action)
        self.statusBar().showMessage("准备就绪")

    def apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #161a20;
                color: #e8edf5;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #303846;
                border-radius: 6px;
                margin-top: 9px;
                padding-top: 12px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QLineEdit, QTextEdit, QPlainTextEdit, QTableWidget, QListWidget, QComboBox {
                background: #202630;
                border: 1px solid #343d4b;
                border-radius: 4px;
                color: #eef3fb;
                selection-background-color: #386a8f;
            }
            QPushButton, QToolButton {
                background: #2e3846;
                border: 1px solid #465365;
                border-radius: 4px;
                padding: 6px 10px;
                color: #eef3fb;
            }
            QPushButton:hover, QToolButton:hover {
                background: #3a4656;
            }
            QPushButton:pressed, QToolButton:pressed {
                background: #26313d;
            }
            QHeaderView::section {
                background: #27303b;
                color: #dfe7f2;
                border: 0;
                border-right: 1px solid #3a4452;
                padding: 6px;
            }
            QTableWidget {
                gridline-color: #313946;
                alternate-background-color: #1c222b;
            }
            QListWidget::item {
                padding: 8px;
            }
            QListWidget::item:selected {
                background: #31506a;
            }
            QTabWidget::pane {
                border: 1px solid #303846;
                border-radius: 6px;
                top: -1px;
            }
            QTabBar::tab {
                background: #202630;
                border: 1px solid #303846;
                border-bottom: 0;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                padding: 8px 18px;
                margin-right: 4px;
                color: #b9c5d6;
            }
            QTabBar::tab:selected {
                background: #2b3542;
                color: #ffffff;
            }
            QLabel#statusChip {
                background: #202630;
                border: 1px solid #343d4b;
                border-radius: 4px;
                padding: 5px 8px;
                color: #cbd7e6;
            }
            #waveformBox {
                background: #11161d;
                border: 1px dashed #465365;
                border-radius: 4px;
                color: #8795a8;
            }
            """
        )

    def restore_settings(self) -> None:
        self.library_path.setText(self.db.get_setting("library_root", ""))
        last_session = self.db.get_setting("last_session_id", "")
        if last_session.isdigit() and self.db.get_session(int(last_session)):
            self.load_session(int(last_session))
        else:
            self.refresh_session_switcher()
            self.update_task_summary()

    def refresh_session_switcher(self) -> None:
        if not hasattr(self, "session_switcher"):
            return
        self.session_switcher_blocked = True
        current_id = self.current_session_id
        self.session_switcher.clear()
        if current_id is None:
            self.session_switcher.addItem("未载入任务", None)

        for session in self.db.list_sessions():
            reaper_mark = " [RPP]" if session.get("reaper_project_path") else ""
            label = f"#{session['id']} {session['title']}{reaper_mark}  {session['updated_at']}"
            self.session_switcher.addItem(label, session["id"])

        if current_id is not None:
            index = self.session_switcher.findData(current_id)
            if index >= 0:
                self.session_switcher.setCurrentIndex(index)
        elif self.session_switcher.count():
            self.session_switcher.setCurrentIndex(0)
        self.session_switcher_blocked = False

    def session_switcher_changed(self, index: int) -> None:
        if self.session_switcher_blocked or index < 0:
            return
        session_id = self.session_switcher.itemData(index)
        if session_id is None or session_id == self.current_session_id:
            return
        self.load_session(int(session_id))

    def toggle_plan_detail(self) -> None:
        if not hasattr(self, "plan_detail_group"):
            return
        visible = not self.plan_detail_group.isVisible()
        self.plan_detail_group.setVisible(visible)
        self.toggle_plan_button.setText("收起需求/方案" if visible else "展开需求/方案")

    def update_task_summary(self) -> None:
        if not hasattr(self, "task_summary_label"):
            return
        if self.current_session_id is None:
            self.task_summary_label.setText("未载入任务。可以从右上任务下拉选择历史需求，或导入 Codex 方案。")
            if hasattr(self, "open_reaper_project_button"):
                self.open_reaper_project_button.setEnabled(False)
                self.open_reaper_project_button.setToolTip("")
            return
        session = self.db.get_session(self.current_session_id)
        if not session:
            self.task_summary_label.setText("当前任务不存在。")
            if hasattr(self, "open_reaper_project_button"):
                self.open_reaper_project_button.setEnabled(False)
                self.open_reaper_project_button.setToolTip("")
            return
        categories = self.db.list_categories(self.current_session_id)
        counts = self.db.result_counts_by_category(self.current_session_id, self.active_library_root())
        result_total = sum(counts.values())
        requirement = " ".join(str(session.get("requirement", "")).split())
        if len(requirement) > 120:
            requirement = requirement[:120] + "..."
        project_path = str(session.get("reaper_project_path") or "")
        project_exists = bool(project_path and Path(project_path).exists())
        project_label = f" | REAPER: {Path(project_path).name}" if project_path else " | REAPER: not linked"
        if hasattr(self, "open_reaper_project_button"):
            self.open_reaper_project_button.setEnabled(project_exists)
            self.open_reaper_project_button.setToolTip(project_path)
        self.task_summary_label.setText(
            f"#{session['id']} {session['title']} | 分类 {len(categories)} | 结果 {result_total}{project_label} | {requirement}"
        )

    def refresh_audio_count(self) -> None:
        root = self.active_library_root()
        current = self.db.count_audio_files(root)
        total = self.db.count_audio_files()
        if root:
            self.audio_count_label.setText(f"索引：{current} / 全部 {total}")
        else:
            self.audio_count_label.setText(f"索引：{total}")

    def active_library_root(self) -> str:
        if not hasattr(self, "library_path"):
            return ""
        return self.library_path.text().strip()

    def _saved_result_limit(self) -> int:
        try:
            value = int(self.db.get_setting("result_limit_per_category", "80"))
        except (TypeError, ValueError):
            value = 80
        return max(1, min(2000, value))

    def _on_result_limit_changed(self, value: int) -> None:
        self.db.set_setting("result_limit_per_category", str(int(value)))

    def result_limit(self) -> int:
        spin = getattr(self, "result_limit_spin", None)
        if spin is not None:
            return int(spin.value())
        return self._saved_result_limit()

    def _toggle_summary_text(self, shown: bool) -> None:
        self.task_summary_label.setVisible(shown)
        self.toggle_summary_button.setText("▾ 摘要" if shown else "▸ 摘要")

    def choose_library(self) -> None:
        start = self.library_path.text() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择音效库根目录", start)
        if not folder:
            return
        self.library_path.setText(folder)
        self.db.set_setting("library_root", folder)

    def scan_library(self) -> None:
        self.start_scan("incremental")

    def rebuild_index(self) -> None:
        root = self.active_library_root()
        if not root:
            QMessageBox.information(self, "需要音效库", "请先选择音效库根目录。")
            return
        reply = QMessageBox.question(
            self,
            "重建索引",
            f"将清空当前音效库的旧索引并重新扫描。\n\n当前根目录：{root}\n\n这不会删除硬盘上的音频文件。",
        )
        if reply != QMessageBox.Yes:
            return
        self.start_scan("rebuild")

    def start_scan(self, mode: str) -> None:
        root_text = self.library_path.text().strip()
        if not root_text:
            QMessageBox.information(self, "需要音效库", "请先选择音效库根目录。")
            return
        root = Path(root_text)
        if not root.exists():
            QMessageBox.warning(self, "目录不存在", f"找不到目录：\n{root}")
            return

        self.scan_button.setEnabled(False)
        if hasattr(self, "rebuild_button"):
            self.rebuild_button.setEnabled(False)
        mode_label = "重建索引" if mode == "rebuild" else "增量扫描"
        if hasattr(self, "task_status_label"):
            self.task_status_label.setText(f"{mode_label}中")
        self.statusBar().showMessage(f"正在{mode_label}...")

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(self.db.path, root, mode)
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.progress.connect(self.scan_progress)
        self.scan_worker.finished.connect(self.scan_finished)
        self.scan_worker.failed.connect(self.scan_failed)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.failed.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.start()

    def scan_progress(self, stats: dict, path: str) -> None:
        processed = int(stats.get("added", 0)) + int(stats.get("updated", 0))
        self.statusBar().showMessage(
            f"扫描中：发现 {stats.get('seen', 0)} / 新增 {stats.get('added', 0)} / "
            f"更新 {stats.get('updated', 0)} / 跳过 {stats.get('skipped', 0)} / 处理 {processed}  {path}"
        )

    def scan_finished(self, stats: dict) -> None:
        self.db = SoundFinderDB()
        self.scan_button.setEnabled(True)
        if hasattr(self, "rebuild_button"):
            self.rebuild_button.setEnabled(True)
        if hasattr(self, "task_status_label"):
            self.task_status_label.setText("后台任务空闲")
        self.refresh_audio_count()
        self.statusBar().showMessage(
            f"扫描完成：发现 {stats.get('seen', 0)}，新增 {stats.get('added', 0)}，"
            f"更新 {stats.get('updated', 0)}，跳过 {stats.get('skipped', 0)}，"
            f"移除旧索引 {stats.get('removed', 0)}。"
        )

    def scan_failed(self, message: str) -> None:
        self.scan_button.setEnabled(True)
        if hasattr(self, "rebuild_button"):
            self.rebuild_button.setEnabled(True)
        if hasattr(self, "task_status_label"):
            self.task_status_label.setText("后台任务空闲")
        QMessageBox.critical(self, "扫描失败", message)
        self.statusBar().showMessage("扫描失败")

    def set_audio_task_busy(self, busy: bool, message: str = "") -> None:
        for name in [
            "local_model_button",
            "search_button",
            "scan_button",
            "rebuild_button",
            "recommend_button",
            "change_recipe_button",
            "layer_search_button",
            "layer_recipe_button",
            "similar_button",
            "open_reaper_project_button",
        ]:
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(not busy)
        self.plan_table.setEnabled(not busy)
        self.category_list.setEnabled(not busy)
        if hasattr(self, "task_status_label"):
            self.task_status_label.setText(message if busy and message else "后台任务空闲")
        if busy and message:
            self.statusBar().showMessage(message)

    def start_audio_task(self, task: str, payload: dict[str, Any], message: str) -> None:
        running_thread = getattr(self, "audio_task_thread", None)
        if running_thread is not None and running_thread.isRunning():
            QMessageBox.information(self, "任务进行中", "当前已有音频搜索任务在运行，请等它完成。")
            return

        self.set_audio_task_busy(True, message)
        self.audio_task_thread = QThread(self)
        self.audio_task_worker = AudioTaskWorker(self.db.path, task, payload)
        self.audio_task_worker.moveToThread(self.audio_task_thread)
        self.audio_task_thread.started.connect(self.audio_task_worker.run)
        self.audio_task_worker.progress.connect(self.audio_task_progress)
        self.audio_task_worker.finished.connect(self.audio_task_finished)
        self.audio_task_worker.failed.connect(self.audio_task_failed)
        self.audio_task_worker.finished.connect(self.audio_task_thread.quit)
        self.audio_task_worker.failed.connect(self.audio_task_thread.quit)
        self.audio_task_thread.finished.connect(self.audio_task_worker.deleteLater)
        self.audio_task_thread.finished.connect(self.audio_task_thread.deleteLater)
        self.audio_task_thread.start()

    def audio_task_progress(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def audio_task_finished(self, result: dict[str, Any]) -> None:
        self.db = SoundFinderDB()
        session_id = result.get("session_id")
        select_category_id = result.get("select_category_id")
        if session_id:
            self.load_session(int(session_id))
            if select_category_id:
                if hasattr(self, "category_filter"):
                    self.category_filter.clear()
                self.populate_categories(select_category_id=int(select_category_id))
                if hasattr(self, "main_tabs"):
                    self.main_tabs.setCurrentIndex(1)
        self.refresh_audio_count()
        self.set_audio_task_busy(False)
        message = result.get("message", "任务完成。")
        self.statusBar().showMessage(message)
        # Make a rule-template fallback impossible to miss: it ignores semantics and
        # just dumps a keyword-matched template, so the user must know it was NOT the model.
        if "rule-fallback" in message or "规则拆解" in message or "模型路由失败" in message:
            QMessageBox.warning(
                self,
                "注意：未使用本地模型",
                "本地模型这次没有成功返回，系统回退到了关键词规则模板（不是真正的语义拆解）。\n\n"
                "请重试一次；若反复失败，检查 Ollama 是否在运行、模型名是否正确。\n\n"
                f"{message}",
            )

    def audio_task_failed(self, message: str) -> None:
        self.set_audio_task_busy(False)
        log_path = Path(__file__).resolve().parents[2] / "sound_finder_errors.log"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("\n=== Audio Task Error ===\n")
            handle.write(message)
            handle.write("\n")
        QMessageBox.critical(
            self,
            "任务失败",
            f"任务执行失败，已写入日志：\n{log_path}\n\n{message.splitlines()[-1] if message else ''}",
        )
        self.statusBar().showMessage("任务失败，已写入错误日志。")

    def clean_old_index(self) -> None:
        root = self.active_library_root()
        if not root:
            QMessageBox.information(self, "需要音效库", "请先选择当前要使用的音效库根目录。")
            return
        before = self.db.count_audio_files()
        current = self.db.count_audio_files(root)
        if current == 0:
            QMessageBox.warning(
                self,
                "当前库没有索引",
                "当前音效库根目录下没有已索引素材。请先扫描当前音效库，再清理旧索引。",
            )
            return
        reply = QMessageBox.question(
            self,
            "清理旧索引",
            f"将删除不在当前音效库根目录内的索引记录。\n\n当前根目录：{root}\n当前库索引：{current}\n全部索引：{before}\n\n这不会删除硬盘上的音频文件。",
        )
        if reply != QMessageBox.Yes:
            return
        removed = self.db.delete_audio_files_outside_library(root)
        removed_unusable = self.db.delete_unusable_audio_files()
        self.db = SoundFinderDB()
        self.refresh_audio_count()
        if self.current_session_id is not None:
            self.populate_categories(select_category_id=self.current_category_id())
        self.statusBar().showMessage(
            f"已清理 {removed} 条旧索引记录，{removed_unusable} 条无效音频索引。"
        )

    def add_empty_category(self) -> None:
        self.fill_plan_table(
            self.read_plan_table()
            + [
                PlanCategory(
                    "新分类",
                    "描述这个按钮或操作需要的声音方向。",
                    ["short UI click", "menu select"],
                    True,
                )
            ]
        )

    def local_model_config(self) -> LocalModelConfig:
        keys = [
            "local_llm_mode",
            "local_llm_provider",
            "local_llm_base_url",
            "local_llm_model",
            "local_llm_api_key",
            "local_llm_remote_base_url",
            "local_llm_remote_model",
            "local_llm_remote_api_key",
            "local_llm_remote_slow_ms",
            "local_llm_temperature",
            "local_llm_timeout",
            "local_llm_max_categories",
            "local_llm_allow_rule_fallback",
        ]
        return config_from_mapping({key: self.db.get_setting(key, "") for key in keys})

    def save_local_model_config(self, config: LocalModelConfig) -> None:
        for key, value in settings_from_config(config).items():
            self.db.set_setting(key, value)

    def local_model_requirement(self) -> None:
        initial_requirement = self.requirement_edit.toPlainText().strip()
        dialog = LocalRequirementDialog(self.local_model_config(), initial_requirement, self)
        if dialog.exec() != QDialog.Accepted:
            return

        config = dialog.selected_config()
        self.save_local_model_config(config)
        if dialog.auto_search_check.isChecked() and self.db.count_audio_files(self.active_library_root()) == 0:
            QMessageBox.information(
                self,
                "还没有索引",
                "请先选择音效库并扫描，或者取消“拆解后直接搜索并生成推荐组合”。",
            )
            return

        if config.mode == "remote":
            model_label = f"远程 {config.remote_model}"
        elif config.mode == "local":
            model_label = f"本地 {config.provider}:{config.model}"
        else:
            model_label = f"自动(远程 {config.remote_model} / 本地 {config.provider}:{config.model})"
        self.start_audio_task(
            "local_requirement",
            {
                "requirement": dialog.requirement(),
                "config": settings_from_config(config),
                "auto_search": dialog.auto_search_check.isChecked(),
                "result_limit": self.result_limit(),
            },
            f"{model_label} 正在拆解需求…（请稍候，本地模型通常 10–30 秒）",
        )

    def import_codex_plan(self) -> None:
        path = CURRENT_PLAN_PATH
        if not path.exists():
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "导入 Codex 方案 JSON",
                str(Path.cwd()),
                "JSON Files (*.json);;All Files (*.*)",
            )
            if not filename:
                return
            path = Path(filename)

        try:
            title, requirement, plan = read_plan_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return

        if not plan:
            QMessageBox.information(self, "方案为空", "这个方案文件里没有可搜索的分类。")
            return

        self.current_session_id = self.db.create_session(title, requirement)
        self.requirement_edit.setPlainText(requirement)
        self.fill_plan_table(plan)
        self.db.replace_plan(self.current_session_id, requirement, plan)
        self.load_session(self.current_session_id)
        self.statusBar().showMessage(f"已导入 Codex 方案：{path}")

    def export_plan(self) -> None:
        plan = self.read_plan_table()
        if not plan:
            QMessageBox.information(self, "没有方案", "当前没有可导出的分类。")
            return
        requirement = self.requirement_edit.toPlainText().strip()
        title = suggest_title(requirement)
        write_plan_file(CURRENT_PLAN_PATH, title, requirement, plan)
        self.statusBar().showMessage(f"已导出：{CURRENT_PLAN_PATH}")

    def fill_plan_table(self, plan: list[PlanCategory]) -> None:
        self.plan_table.setRowCount(0)
        for category in plan:
            row = self.plan_table.rowCount()
            self.plan_table.insertRow(row)

            include_item = QTableWidgetItem()
            include_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            include_item.setCheckState(Qt.Checked if category.include else Qt.Unchecked)
            self.plan_table.setItem(row, 0, include_item)

            style = category.recipe_style or "realistic_tactile"
            recipe = category.recipe or build_recipe_for_category(
                {
                    "name": category.name,
                    "direction": category.direction,
                    "keywords": category.keywords,
                    "recipe_style": style,
                },
                style,
            )

            name_item = QTableWidgetItem(category.name)
            name_item.setData(Qt.UserRole, recipe)
            name_item.setData(Qt.UserRole + 1, style)
            self.plan_table.setItem(row, 1, name_item)

            style_item = QTableWidgetItem(STYLE_LABELS.get(style, style))
            style_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            style_item.setData(Qt.UserRole, style)
            self.plan_table.setItem(row, 2, style_item)
            self.plan_table.setItem(row, 3, QTableWidgetItem(category.direction))
            self.plan_table.setItem(row, 4, QTableWidgetItem(", ".join(category.keywords)))

    def read_plan_table(self) -> list[PlanCategory]:
        plan: list[PlanCategory] = []
        for row in range(self.plan_table.rowCount()):
            include = self.plan_table.item(row, 0).checkState() == Qt.Checked
            name_item = self.plan_table.item(row, 1)
            style_item = self.plan_table.item(row, 2)
            name = self.item_text(row, 1)
            direction = self.item_text(row, 3)
            keywords = [
                token.strip()
                for token in self.item_text(row, 4).replace("\n", ",").split(",")
                if token.strip()
            ]
            if not name or not keywords:
                continue

            style = style_item.data(Qt.UserRole) if style_item else "realistic_tactile"
            recipe = name_item.data(Qt.UserRole) if name_item else []
            if not recipe:
                recipe = build_recipe_for_category(
                    {"name": name, "direction": direction, "keywords": keywords},
                    style,
                )
            plan.append(PlanCategory(name, direction, keywords, include, recipe, style))
        return plan

    def item_text(self, row: int, column: int) -> str:
        item = self.plan_table.item(row, column)
        return item.text().strip() if item else ""

    def save_plan(self) -> int | None:
        plan = self.read_plan_table()
        if not plan:
            QMessageBox.information(self, "没有方案", "请先导入或手动添加分类。")
            return None
        requirement = self.requirement_edit.toPlainText().strip()
        if self.current_session_id is None:
            self.current_session_id = self.db.create_session(suggest_title(requirement), requirement)
        self.db.replace_plan(self.current_session_id, requirement, plan)
        self.db.set_setting("last_session_id", str(self.current_session_id))
        self.update_task_summary()
        return self.current_session_id

    def save_plan_only(self) -> None:
        session_id = self.save_plan()
        if session_id:
            self.load_session(session_id)
            self.statusBar().showMessage("方案已保存。")

    def confirm_and_search(self) -> None:
        if self.db.count_audio_files(self.active_library_root()) == 0:
            QMessageBox.information(self, "还没有索引", "请先选择音效库并扫描。")
            return

        plan = self.read_plan_table()
        if not plan:
            QMessageBox.information(self, "没有方案", "请先导入 Codex 方案或手动添加分类。")
            return

        requirement = self.requirement_edit.toPlainText().strip()
        if self.current_session_id is None:
            self.current_session_id = self.db.create_session(suggest_title(requirement), requirement)

        self.start_audio_task(
            "confirm_search",
            {
                "session_id": self.current_session_id,
                "requirement": requirement,
                "plan": plan,
                "result_limit": self.result_limit(),
            },
            "正在后台搜索本地音效库...",
        )

    def load_history(self) -> None:
        sessions = self.db.list_sessions()
        if not sessions:
            QMessageBox.information(self, "暂无历史", "还没有保存过需求。")
            return
        dialog = HistoryDialog(sessions, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_session_id:
            self.load_session(dialog.selected_session_id)

    def load_session(self, session_id: int) -> None:
        session = self.db.get_session(session_id)
        if not session:
            return
        self.current_session_id = session_id
        if self.db.get_setting("last_session_id", "") != str(session_id):
            self.db.set_setting("last_session_id", str(session_id))
        self.requirement_edit.setPlainText(session["requirement"])
        categories = self.db.list_categories(session_id)
        plan = [
            PlanCategory(
                category["name"],
                category["direction"],
                category["keywords"],
                category["include"],
                category.get("recipe", []),
                category.get("recipe_style", "realistic_tactile"),
            )
            for category in categories
        ]
        self.fill_plan_table(plan)
        self.populate_categories()
        self.refresh_session_switcher()
        self.update_task_summary()
        self.statusBar().showMessage(f"已载入：{session['title']}")

    def populate_categories(self, select_category_id: int | None = None) -> None:
        self.category_list.blockSignals(True)
        self.category_list.clear()
        if self.current_session_id is None:
            self.category_list.blockSignals(False)
            return
        filter_text = ""
        if hasattr(self, "category_filter"):
            filter_text = self.category_filter.text().strip().lower()

        total_results = len(
            self.db.list_results(
                self.current_session_id,
                library_root=self.active_library_root(),
            )
        )
        all_item = QListWidgetItem(f"全部结果 ({total_results})")
        all_item.setData(Qt.UserRole, None)
        self.category_list.addItem(all_item)

        counts = self.db.result_counts_by_category(self.current_session_id, self.active_library_root())
        select_row = 0
        for category in self.db.list_categories(self.current_session_id):
            haystack = " ".join(
                [
                    category["name"],
                    category["direction"],
                    ", ".join(category["keywords"]),
                ]
            ).lower()
            if filter_text and filter_text not in haystack:
                continue
            count = counts.get(category["id"], 0)
            item = QListWidgetItem(f"{category['name']} ({count})")
            item.setData(Qt.UserRole, category["id"])
            self.category_list.addItem(item)
            if select_category_id == category["id"]:
                select_row = self.category_list.count() - 1

        if select_category_id is None and self.category_list.count() > 1:
            select_row = 1

        self.category_list.blockSignals(False)
        self.category_list.setCurrentRow(select_row)
        self.category_changed()

    def category_changed(self) -> None:
        if self.current_session_id is None:
            return
        category_id = self.current_category_id()
        self.current_results = self.db.list_results(
            self.current_session_id,
            category_id,
            self.active_library_root(),
        )
        self.current_layer_index = None
        self.display_current_recipe()
        self.populate_recommendation_table()
        self.populate_layer_table(select_first=True)
        self.populate_combo_history()
        self.populate_result_table()

    def current_category_id(self) -> int | None:
        item = self.category_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def current_category(self) -> dict[str, Any] | None:
        if self.current_session_id is None:
            return None
        category_id = self.current_category_id()
        if category_id is None:
            return None
        for category in self.db.list_categories(self.current_session_id):
            if category["id"] == category_id:
                return category
        return None

    def style_display_label(self, style: str) -> str:
        if style.startswith("custom:"):
            base_style = style.split(":", 1)[1]
            return f"混合 Layer 配方 / 最近替换来源：{STYLE_LABELS.get(base_style, base_style)}"
        return STYLE_LABELS.get(style, style)

    def next_recipe_style_code(self, category: dict[str, Any]) -> str:
        current = str(category.get("recipe_style", "realistic_tactile"))
        if current.startswith("custom:"):
            current = current.split(":", 1)[1]
        probe = dict(category)
        probe["recipe_style"] = current
        return next_style_for_category(probe)

    def current_layer(self) -> dict[str, Any] | None:
        category = self.current_category()
        if not category:
            return None
        recipe = category.get("recipe", [])
        if self.current_layer_index is None:
            return None
        if self.current_layer_index < 0 or self.current_layer_index >= len(recipe):
            return None
        return recipe[self.current_layer_index]

    def display_current_recipe(self) -> None:
        category = self.current_category()
        if not category:
            self.recipe_text.setPlainText("选择一个具体分类后可以查看配方、推荐组合、改变配方或随机替换素材。")
            return

        lines = [self.style_display_label(str(category.get("recipe_style", "realistic_tactile")))]
        for index, layer in enumerate(category.get("recipe", []), start=1):
            keywords = ", ".join(layer.get("keywords", [])[:5])
            lines.append(f"{index}. {layer.get('name', 'Layer')}: {layer.get('role', '')}")
            lines.append(f"  {keywords}")
        self.recipe_text.setPlainText("\n".join(lines))

    def populate_result_table(self) -> None:
        if not hasattr(self, "result_table"):
            return

        filter_text = self.filter_edit.text().strip().lower()
        favorite_only = self.favorites_only.isChecked()
        used_only = self.used_only.isChecked()
        layer = self.current_layer()
        layer_keywords = layer.get("keywords", []) if layer else []
        layer_weight = float(layer.get("weight", 1.0)) if layer else 1.0

        filtered: list[dict[str, Any]] = []
        for result in self.current_results:
            display_result = dict(result)
            if layer_keywords:
                layer_score, layer_matched = score_file(result, layer_keywords)
                if layer_score <= 0:
                    continue
                display_result["score"] = round(
                    layer_score * layer_weight + float(result.get("score", 0.0)) * 0.08,
                    2,
                )
                display_result["matched_terms"] = ", ".join(layer_matched)
            haystack = " ".join(
                [
                    display_result["name"],
                    display_result["folder"],
                    str(display_result["matched_terms"]),
                    display_result["category_name"],
                ]
            ).lower()
            if filter_text and filter_text not in haystack:
                continue
            if favorite_only and not display_result["favorite"]:
                continue
            if used_only and not display_result["used"]:
                continue
            filtered.append(display_result)

        if layer_keywords:
            filtered.sort(key=lambda row: (-float(row["score"]), row["name"].lower()))

        self.result_table.setRowCount(0)
        for result in filtered:
            row = self.result_table.rowCount()
            self.result_table.insertRow(row)

            score_item = QTableWidgetItem(f"{result['score']:.0f}")
            score_item.setData(Qt.UserRole, result["path"])
            score_item.setData(Qt.UserRole + 1, result)
            self.result_table.setItem(row, 0, score_item)
            self.result_table.setItem(row, 1, QTableWidgetItem(result["name"]))
            self.result_table.setItem(row, 2, QTableWidgetItem(format_duration(result["duration"])))
            self.result_table.setItem(row, 3, QTableWidgetItem(result["category_name"]))
            self.result_table.setItem(row, 4, QTableWidgetItem(result["matched_terms"]))
            self.result_table.setItem(row, 5, QTableWidgetItem("★" if result["favorite"] else ""))
            self.result_table.setItem(row, 6, QTableWidgetItem("✓" if result["used"] else ""))

        self.result_table.resizeRowsToContents()
        if filtered:
            self.result_table.selectRow(0)
        else:
            self.clear_detail()

    def result_selection_changed(self) -> None:
        row = self.result_table.currentRow()
        if row < 0:
            self.clear_detail()
            return

        item = self.result_table.item(row, 0)
        result = item.data(Qt.UserRole + 1) if item else None
        if not result:
            self.clear_detail()
            return
        self.show_result_detail(result)

    def show_result_detail(self, result: dict[str, Any]) -> None:
        self.selected_result = result
        self.detail_name.setText(result["name"])
        self.detail_meta.setText(
            f"分类：{result.get('category_name', '')}    分数：{float(result.get('score', 0)):.0f}    "
            f"格式：{result.get('extension', '')}    时长：{format_duration(result.get('duration')) or '未知'}"
        )
        self.detail_path.setPlainText(result["path"])
        self.keyword_text.setPlainText(result.get("matched_terms", result.get("reason", "")))
        selected_paths = self.selected_result_paths() or [result["path"]]
        self.drag_label.set_paths(selected_paths)
        analysis = self.audio_analysis_for_path(result["path"])
        self.audio_stats_label.setText(format_audio_analysis(analysis))
        self.waveform_placeholder.set_waveform(
            analysis.get("waveform", []),
            str(analysis.get("error", "")),
        )

    def selected_result_paths(self) -> list[str]:
        if hasattr(self, "result_table"):
            return self.result_table.selected_paths()
        return [self.selected_result["path"]] if self.selected_result else []

    def audio_analysis_for_path(self, path: str) -> dict[str, Any]:
        if path in self.audio_analysis_cache:
            return self.audio_analysis_cache[path]
        analysis = analyze_audio(Path(path))
        if len(self.audio_analysis_cache) > 128:
            self.audio_analysis_cache.pop(next(iter(self.audio_analysis_cache)))
        self.audio_analysis_cache[path] = analysis
        return analysis

    def auto_play_selected_after_click(self, *_: Any) -> None:
        self.player.stop()
        QTimer.singleShot(0, self.play_selected)

    def clear_detail(self) -> None:
        self.player.stop()
        self.selected_result = None
        self.detail_name.setText("未选择文件")
        self.detail_meta.setText("")
        self.detail_path.setPlainText("")
        self.keyword_text.setPlainText("")
        self.drag_label.set_path("")
        if hasattr(self, "audio_stats_label"):
            self.audio_stats_label.setText("Ch: -    SR: -    Bit: -    Duration: -    Peak: -    RMS: -    LUFS-I≈: -")
        if hasattr(self, "waveform_placeholder") and hasattr(self.waveform_placeholder, "clear"):
            self.waveform_placeholder.clear()

    def populate_layer_table(self, select_first: bool = False) -> None:
        self.layer_table.blockSignals(True)
        self.layer_table.setRowCount(0)
        self.layer_detail_text.clear()

        category = self.current_category()
        if not category:
            self.current_layer_index = None
            self.layer_table.blockSignals(False)
            return

        recipe = category.get("recipe", [])
        recs = {
            rec["layer_name"]: rec
            for rec in self.db.list_recommendations(
                self.current_session_id,
                category["id"],
                self.active_library_root(),
            )
        }

        for index, layer in enumerate(recipe):
            row = self.layer_table.rowCount()
            self.layer_table.insertRow(row)
            number_item = QTableWidgetItem(str(index + 1))
            number_item.setData(Qt.UserRole, index)
            self.layer_table.setItem(row, 0, number_item)
            self.layer_table.setItem(row, 1, QTableWidgetItem(layer.get("name", f"Layer {index + 1}")))

            rec = recs.get(layer.get("name", ""))
            self.layer_table.setItem(row, 2, QTableWidgetItem(rec["name"] if rec else "未推荐"))
            self.layer_table.setItem(row, 3, QTableWidgetItem(f"{rec['score']:.0f}" if rec else ""))

        self.layer_table.resizeRowsToContents()
        if recipe:
            if select_first or self.current_layer_index is None or self.current_layer_index >= len(recipe):
                self.current_layer_index = 0
            self.layer_table.selectRow(self.current_layer_index)
            self.update_layer_detail()
        else:
            self.current_layer_index = None

        self.layer_table.blockSignals(False)

    def update_layer_detail(self) -> None:
        layer = self.current_layer()
        if not layer:
            self.layer_detail_text.setPlainText("当前分类没有可操作的 Layer。")
            return
        keywords = ", ".join(layer.get("keywords", []))
        self.layer_detail_text.setPlainText(
            f"{layer.get('name', 'Layer')}\n{layer.get('role', '')}\n关键词：{keywords}"
        )

    def layer_selection_changed(self) -> None:
        row = self.layer_table.currentRow()
        if row < 0:
            self.current_layer_index = None
            self.update_layer_detail()
            self.populate_result_table()
            return

        item = self.layer_table.item(row, 0)
        self.current_layer_index = int(item.data(Qt.UserRole)) if item else row
        self.update_layer_detail()
        self.populate_result_table()

        layer = self.current_layer()
        if not layer:
            return
        target_rec: dict[str, Any] | None = None
        self.recommendation_table.blockSignals(True)
        for rec_row in range(self.recommendation_table.rowCount()):
            rec_item = self.recommendation_table.item(rec_row, 0)
            if rec_item and rec_item.text() == layer.get("name", ""):
                target_rec = rec_item.data(Qt.UserRole)
                self.recommendation_table.selectRow(rec_row)
                break
        self.recommendation_table.blockSignals(False)
        if target_rec:
            self.select_result_by_audio_id(target_rec["audio_file_id"])

    def populate_combo_history(self) -> None:
        self.combo_history_list.clear()
        if self.current_session_id is None:
            return
        category = self.current_category()
        if not category:
            return
        for item in self.db.list_combo_history(self.current_session_id, category["id"]):
            label = f"{item['created_at']}  {item['title']}"
            history_item = QListWidgetItem(label)
            history_item.setData(Qt.UserRole, item["id"])
            self.combo_history_list.addItem(history_item)

    def combo_history_title(self, source: str, recommendations: list[dict[str, Any]]) -> str:
        layer_names = [item.get("layer_name", "Layer") for item in recommendations]
        source_label = {
            "recommend": "推荐组合",
            "recipe_changed": "整体配方",
            "layer_researched": "重搜 Layer",
            "layer_recipe_changed": "替换 Layer",
            "similar_random": "相似替换",
        }.get(source, source)
        return f"{source_label} / {len(layer_names)}层 / {' + '.join(layer_names[:4])}"

    def record_combo_history(
        self,
        category: dict[str, Any],
        source: str,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> None:
        if self.current_session_id is None:
            return
        recommendations = recommendations or self.db.list_recommendations(
            self.current_session_id,
            category["id"],
            self.active_library_root(),
        )
        if not recommendations:
            return
        self.db.save_combo_history(
            self.current_session_id,
            category["id"],
            title=self.combo_history_title(source, recommendations),
            source=source,
            recipe_style=str(category.get("recipe_style", "realistic_tactile")),
            recipe=category.get("recipe", []),
            recommendations=recommendations,
            results=self.db.list_results(
                self.current_session_id,
                category["id"],
                self.active_library_root(),
            ),
        )
        self.populate_combo_history()

    def populate_recommendation_table(self) -> None:
        self.recommendation_table.setRowCount(0)
        if self.current_session_id is None:
            return
        category_id = self.current_category_id()
        if category_id is None:
            return
        for rec in self.db.list_recommendations(
            self.current_session_id,
            category_id,
            self.active_library_root(),
        ):
            row = self.recommendation_table.rowCount()
            self.recommendation_table.insertRow(row)
            layer_item = QTableWidgetItem(rec["layer_name"])
            layer_item.setData(Qt.UserRole, rec)
            self.recommendation_table.setItem(row, 0, layer_item)
            self.recommendation_table.setItem(row, 1, QTableWidgetItem(rec["name"]))
            self.recommendation_table.setItem(row, 2, QTableWidgetItem(f"{rec['score']:.0f}"))
            self.recommendation_table.setItem(row, 3, QTableWidgetItem(rec["reason"]))
        self.recommendation_table.resizeRowsToContents()

    def recommendation_selection_changed(self) -> None:
        row = self.recommendation_table.currentRow()
        if row < 0:
            return
        item = self.recommendation_table.item(row, 0)
        rec = item.data(Qt.UserRole) if item else None
        if not rec:
            return
        category = self.current_category()
        if category:
            for index, layer in enumerate(category.get("recipe", [])):
                if layer.get("name") == rec.get("layer_name"):
                    self.current_layer_index = index
                    self.layer_table.blockSignals(True)
                    self.layer_table.selectRow(index)
                    self.layer_table.blockSignals(False)
                    self.update_layer_detail()
                    self.populate_result_table()
                    break
        self.select_result_by_audio_id(rec["audio_file_id"])

    def select_result_by_audio_id(self, audio_file_id: int) -> None:
        for row in range(self.result_table.rowCount()):
            item = self.result_table.item(row, 0)
            result = item.data(Qt.UserRole + 1) if item else None
            if result and result["audio_file_id"] == audio_file_id:
                self.result_table.selectRow(row)
                return

    def recommend_all_categories(self, session_id: int) -> None:
        for category in self.db.list_categories(session_id):
            results = self.db.list_results(
                session_id,
                category["id"],
                self.active_library_root(),
            )
            recommendations = make_recommendations(category, results)
            if recommendations:
                self.db.save_recommendations(
                    session_id,
                    category["id"],
                    recommendations,
                    "recommend",
                )
                self.db.save_combo_history(
                    session_id,
                    category["id"],
                    title=self.combo_history_title("recommend", recommendations),
                    source="recommend",
                    recipe_style=str(category.get("recipe_style", "realistic_tactile")),
                    recipe=category.get("recipe", []),
                    recommendations=recommendations,
                    results=self.db.list_results(
                        session_id,
                        category["id"],
                        self.active_library_root(),
                    ),
                )

    def recommend_current_category(self) -> None:
        if self.current_session_id is None:
            return
        category = self.current_category()
        if not category:
            QMessageBox.information(self, "选择分类", "请先在左侧选择一个具体分类。")
            return
        results = self.db.list_results(
            self.current_session_id,
            category["id"],
            self.active_library_root(),
        )
        recommendations = make_recommendations(category, results)
        if not recommendations:
            QMessageBox.information(self, "没有推荐", "当前分类没有足够的搜索结果可组合。")
            return
        self.db.save_recommendations(
            self.current_session_id,
            category["id"],
            recommendations,
            "recommend",
        )
        self.populate_recommendation_table()
        self.populate_layer_table()
        self.record_combo_history(category, "recommend", recommendations)
        self.statusBar().showMessage(f"已为 {category['name']} 生成推荐组合。")

    def change_recipe(self) -> None:
        if self.current_session_id is None:
            return
        category = self.current_category()
        if not category:
            QMessageBox.information(self, "选择分类", "请先在左侧选择一个具体分类。")
            return

        new_style = self.next_recipe_style_code(category)
        self.start_audio_task(
            "change_recipe",
            {
                "session_id": self.current_session_id,
                "category": category,
                "new_style": new_style,
            },
            f"正在后台切换 {category['name']} 的整体配方...",
        )

    def random_similar_material(self) -> None:
        if self.current_session_id is None:
            return
        category = self.current_category()
        if not category:
            QMessageBox.information(self, "选择分类", "请先在左侧选择一个具体分类。")
            return

        recs = self.db.list_recommendations(
            self.current_session_id,
            category["id"],
            self.active_library_root(),
        )
        if not recs:
            self.recommend_current_category()
            recs = self.db.list_recommendations(
                self.current_session_id,
                category["id"],
                self.active_library_root(),
            )
        if not recs:
            return

        row = self.recommendation_table.currentRow()
        target_index = row if row >= 0 and row < len(recs) else 0
        target = recs[target_index]

        layer = None
        for item in category.get("recipe", []):
            if item.get("name") == target["layer_name"]:
                layer = item
                break
        if layer is None:
            QMessageBox.information(self, "找不到 layer", "当前推荐对应的 layer 已不存在。")
            return

        avoid_ids = {rec["audio_file_id"] for index, rec in enumerate(recs) if index != target_index}
        replacement = similar_replacement(
            layer,
            target,
            self.db.list_results(
                self.current_session_id,
                category["id"],
                self.active_library_root(),
            ),
            avoid_ids,
        )
        if replacement is None:
            QMessageBox.information(self, "没有相似替代", "当前搜索结果里找不到足够接近的替代素材。")
            return

        updated: list[dict[str, Any]] = []
        for index, rec in enumerate(recs):
            if index == target_index:
                updated.append(replacement)
            else:
                updated.append(
                    {
                        "layer_name": rec["layer_name"],
                        "layer_role": rec["layer_role"],
                        "audio_file_id": rec["audio_file_id"],
                        "score": rec["score"],
                        "reason": rec["reason"],
                    }
                )
        self.db.save_recommendations(
            self.current_session_id,
            category["id"],
            updated,
            "similar_random",
        )
        self.populate_recommendation_table()
        self.populate_layer_table()
        self.record_combo_history(category, "similar_random", updated)
        self.recommendation_table.selectRow(target_index)
        self.statusBar().showMessage(f"{target['layer_name']} 已替换为相似素材。")

    def recommendation_list_with_layer(
        self,
        category: dict[str, Any],
        layer: dict[str, Any],
        new_recommendation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        recs = self.db.list_recommendations(
            self.current_session_id,
            category["id"],
            self.active_library_root(),
        )
        rec_by_layer = {rec["layer_name"]: rec for rec in recs}
        rec_by_layer[layer.get("name", "Layer")] = new_recommendation

        ordered: list[dict[str, Any]] = []
        for recipe_layer in category.get("recipe", []):
            rec = rec_by_layer.get(recipe_layer.get("name", ""))
            if not rec:
                continue
            ordered.append(
                {
                    "layer_name": rec["layer_name"],
                    "layer_role": rec["layer_role"],
                    "audio_file_id": rec["audio_file_id"],
                    "score": rec["score"],
                    "reason": rec["reason"],
                }
            )
        return ordered

    def research_current_layer(self) -> None:
        if self.current_session_id is None:
            return
        category = self.current_category()
        layer = self.current_layer()
        if not category or not layer:
            QMessageBox.information(self, "选择 Layer", "请先选择一个具体分类和配方 Layer。")
            return

        self.start_audio_task(
            "research_layer",
            {
                "session_id": self.current_session_id,
                "category": category,
                "layer": layer,
            },
            f"正在后台重搜 {category['name']} / {layer.get('name', 'Layer')}...",
        )

    def replace_current_layer_recipe(self) -> None:
        if self.current_session_id is None:
            return
        category = self.current_category()
        layer = self.current_layer()
        if not category or not layer or self.current_layer_index is None:
            QMessageBox.information(self, "选择 Layer", "请先选择一个具体分类和配方 Layer。")
            return

        new_style = self.next_recipe_style_code(category)
        self.start_audio_task(
            "replace_layer_recipe",
            {
                "session_id": self.current_session_id,
                "category": category,
                "layer": layer,
                "layer_index": self.current_layer_index,
                "new_style": new_style,
            },
            f"正在后台替换 {category['name']} / 第 {self.current_layer_index + 1} 层配方...",
        )

    def restore_selected_combo_history(self) -> None:
        if self.current_session_id is None:
            return
        item = self.combo_history_list.currentItem()
        if not item:
            QMessageBox.information(self, "选择历史", "请先在组合历史里选择一个记录。")
            return
        history_id = int(item.data(Qt.UserRole))
        history = self.db.get_combo_history(history_id)
        if not history:
            QMessageBox.warning(self, "历史不存在", "这条组合历史已经不存在。")
            return

        self.db.update_category_recipe(
            history["category_id"],
            recipe=history["recipe"],
            recipe_style=history["recipe_style"],
        )
        if history["results"]:
            self.db.replace_category_results_from_history(
                history["session_id"],
                history["category_id"],
                history["results"],
            )
        self.db.save_recommendations(
            history["session_id"],
            history["category_id"],
            history["recommendations"],
            "history_restore",
        )
        self.load_session(history["session_id"])
        self.populate_categories(select_category_id=history["category_id"])
        self.statusBar().showMessage(f"已恢复组合历史：{history['title']}")

    def play_selected(self) -> None:
        if not self.selected_result:
            return
        path = self.selected_result["path"]
        self.player.stop()
        if not Path(path).exists():
            QMessageBox.warning(self, "文件不存在", path)
            return
        self.player.setSource(QUrl.fromLocalFile(path))
        if hasattr(self, "waveform_placeholder"):
            self.waveform_placeholder.set_playback_ratio(0.0)
        self.player.setPosition(0)
        self.player.play()

    def play_from_waveform_ratio(self, ratio: float) -> None:
        if not self.selected_result:
            return
        path = self.selected_result["path"]
        if not Path(path).exists():
            QMessageBox.warning(self, "文件不存在", path)
            return
        duration = self.audio_analysis_for_path(path).get("duration") or self.selected_result.get("duration")
        if not duration:
            return
        clean_ratio = max(0.0, min(1.0, ratio))
        position_ms = int(clean_ratio * float(duration) * 1000)
        self.waveform_placeholder.set_playback_ratio(clean_ratio)
        self.pending_seek_position_ms = position_ms
        self.pending_seek_path = path
        if self.player_source_matches(path):
            self.apply_pending_seek()
            return
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(path))
        QTimer.singleShot(80, self.apply_pending_seek)

    def player_source_matches(self, path: str) -> bool:
        current = self.player.source().toLocalFile()
        if not current:
            return False
        return Path(current).as_posix().lower() == Path(path).as_posix().lower()

    def player_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        ready_statuses = {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }
        if status in ready_statuses:
            self.apply_pending_seek()

    def apply_pending_seek(self) -> None:
        if self.pending_seek_position_ms is None:
            return
        if self.pending_seek_path and not self.player_source_matches(self.pending_seek_path):
            return
        position_ms = self.pending_seek_position_ms
        self.pending_seek_position_ms = None
        self.pending_seek_path = ""
        self.start_player_at_position(position_ms)

    def start_player_at_position(self, position_ms: int) -> None:
        self.player.setPosition(position_ms)
        self.player.play()

    def player_position_changed(self, position_ms: int) -> None:
        if not self.selected_result or not hasattr(self, "waveform_placeholder"):
            return
        duration = self.audio_analysis_for_path(self.selected_result["path"]).get("duration") or self.selected_result.get("duration")
        if not duration:
            return
        self.waveform_placeholder.set_playback_ratio(position_ms / max(1.0, float(duration) * 1000))

    def toggle_favorite(self) -> None:
        if not self.selected_result or "result_id" not in self.selected_result:
            return
        new_value = not bool(self.selected_result["favorite"])
        self.db.update_result_flags(self.selected_result["result_id"], favorite=new_value)
        self.reload_current_category(keep_result_id=self.selected_result["result_id"])

    def toggle_used(self) -> None:
        if not self.selected_result or "result_id" not in self.selected_result:
            return
        new_value = not bool(self.selected_result["used"])
        self.db.update_result_flags(self.selected_result["result_id"], used=new_value)
        self.reload_current_category(keep_result_id=self.selected_result["result_id"])

    def reload_current_category(self, keep_result_id: int | None = None) -> None:
        self.category_changed()
        if keep_result_id is None:
            return
        for row in range(self.result_table.rowCount()):
            item = self.result_table.item(row, 0)
            result = item.data(Qt.UserRole + 1) if item else None
            if result and result["result_id"] == keep_result_id:
                self.result_table.selectRow(row)
                break

    def open_selected_location(self) -> None:
        if not self.selected_result:
            return
        path = self.selected_result["path"]
        subprocess.Popen(["explorer", "/select,", path])

    def copy_selected_path(self) -> None:
        if not self.selected_result:
            return
        paths = self.selected_result_paths() or [self.selected_result["path"]]
        QApplication.clipboard().setText("\n".join(paths))
        self.statusBar().showMessage(f"已复制 {len(paths)} 个路径。")

    def open_current_reaper_project(self) -> None:
        if self.current_session_id is None:
            QMessageBox.information(self, "No session", "Load a Sound Finder requirement first.")
            return
        session = self.db.get_session(self.current_session_id)
        if not session:
            QMessageBox.warning(self, "No session", "The current Sound Finder session no longer exists.")
            return
        project_text = str(session.get("reaper_project_path") or "").strip()
        if not project_text:
            QMessageBox.warning(
                self,
                "REAPER project not linked",
                "This requirement has no saved REAPER project yet. Use REAPER Tracks first.",
            )
            self.update_task_summary()
            return
        project_path = Path(project_text)
        if not project_path.exists():
            QMessageBox.warning(
                self,
                "REAPER project not found",
                "This requirement has no saved REAPER project yet. Use REAPER Tracks first.",
            )
            self.update_task_summary()
            return
        subprocess.Popen([str(reaper_exe_path()), "-newinst", str(project_path)])
        self.statusBar().showMessage(f"Opened REAPER project: {project_path.name}")

    def create_reaper_requirement_tracks(self) -> None:
        if self.current_session_id is None:
            QMessageBox.warning(self, "未载入需求", "请先载入或保存一个 Sound Finder 需求。")
            return

        session = self.db.get_session(self.current_session_id)
        if not session:
            QMessageBox.warning(self, "未找到需求", "当前 Sound Finder session 不存在。")
            return

        categories = self.db.list_categories(self.current_session_id)
        if not categories:
            QMessageBox.warning(self, "没有分类", "当前需求没有可用于建轨的分类。")
            return

        # Group (parent track) name: default to this task's name, but let the user
        # edit it or clear it to leave the folder track unnamed (filled in manually).
        default_group = re.sub(r"^\d{4}-\d{2}-\d{2}\s+", "", str(session.get("title", ""))).strip()[:32]
        group_name, ok_dialog = QInputDialog.getText(
            self,
            "REAPER 分组名",
            "分组(父轨)名称——留空则不命名,可填本次任务名：",
            QLineEdit.Normal,
            default_group,
        )
        if not ok_dialog:
            return
        group_name = group_name.strip()

        ok, message, project_name, project_path = create_or_update_reaper_project(
            self.current_session_id,
            str(session.get("title", "")),
            str(session.get("requirement", "")),
            categories,
            group_name=group_name,
        )
        if ok:
            self.db.update_session_reaper_project(
                self.current_session_id,
                project_name=project_name,
                project_path=project_path,
            )
            self.refresh_session_switcher()
            self.update_task_summary()
            self.statusBar().showMessage(f"Created/updated REAPER project: {project_path}")
            QMessageBox.information(
                self,
                "REAPER project updated",
                (
                    f"Project: {project_name}\n"
                    f"Path: {project_path}\n\n"
                    f"分组: {group_name or '(未命名)'} + {len(categories)} 条需求轨。"
                ),
            )
            return

        self.statusBar().showMessage("Failed to create REAPER project.")
        QMessageBox.warning(
            self,
            "Create failed",
            f"REAPER did not confirm project creation.\n\n{message}",
        )

    def export_soundly_sheet(self) -> None:
        if self.current_session_id is None:
            QMessageBox.warning(self, "未载入需求", "请先载入或保存一个 Sound Finder 需求。")
            return

        session = self.db.get_session(self.current_session_id)
        if not session:
            QMessageBox.warning(self, "未找到需求", "当前 Sound Finder session 不存在。")
            return

        categories = self.db.list_categories(self.current_session_id)
        if not categories:
            QMessageBox.warning(self, "没有分类", "当前需求没有可导出的分类。")
            return

        csv_path, md_path = export_soundly_search_sheet(
            self.current_session_id,
            str(session.get("title", "")),
            categories,
        )
        self.statusBar().showMessage(f"已导出 Soundly 筛选表：{csv_path.name}")
        subprocess.Popen(["explorer", "/select,", str(csv_path)])
        QMessageBox.information(
            self,
            "Soundly 筛选表已导出",
            f"已导出 {len(categories)} 条需求。\n\nCSV: {csv_path}\nMarkdown: {md_path}",
        )

    def clear_current(self) -> None:
        self.current_session_id = None
        self.current_results = []
        self.current_layer_index = None
        self.selected_result = None
        self.requirement_edit.clear()
        self.plan_table.setRowCount(0)
        self.category_list.clear()
        self.result_table.setRowCount(0)
        self.layer_table.setRowCount(0)
        self.recommendation_table.setRowCount(0)
        self.combo_history_list.clear()
        self.layer_detail_text.clear()
        self.recipe_text.clear()
        self.clear_detail()
        self.refresh_session_switcher()
        self.update_task_summary()
        self.statusBar().showMessage("当前工作区已清空，历史记录仍保留。")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
