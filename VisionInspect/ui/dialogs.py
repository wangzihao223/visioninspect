"""对话框模块.

包含：
    - 模型选择对话框
    - 缺陷关联对话框
    - 统计图表展示对话框
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)


class ModelSelectDialog(QDialog):
    """模型选择对话框.

    选择 .pt 模型文件，可配置是否强制重新识别。
    """

    def __init__(self, parent=None, last_model: str = ""):
        super().__init__(parent)
        self.setWindowTitle("模型识别")
        self.setMinimumWidth(480)
        self.model_path = ""
        self.force = False

        layout = QVBoxLayout(self)

        # 模型文件选择
        form = QFormLayout()
        self.model_edit = QLineEdit(last_model)
        self.model_edit.setPlaceholderText("请选择 .pt 模型文件")
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_model)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_edit)
        model_row.addWidget(browse_btn)
        form.addRow("模型文件:", model_row)

        layout.addLayout(form)

        # 选项
        self.force_check = QCheckBox("强制重新识别（忽略已有 JSON 结果）")
        layout.addWidget(self.force_check)

        # 提示
        hint = QLabel(
            "提示：识别结果将保存为图片同名 JSON 文件。\n"
            "如 JSON 已存在，默认跳过该图片。"
        )
        hint.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(hint)

        # 按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _browse_model(self):
        """浏览选择模型文件."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 YOLO 模型",
            "",
            "YOLO 模型 (*.pt)",
        )
        if path:
            self.model_edit.setText(path)

    def _on_accept(self):
        """确认."""
        path = self.model_edit.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "警告", "请选择有效的模型文件")
            return
        self.model_path = path
        self.force = self.force_check.isChecked()
        self.accept()


class DefectBindDialog(QDialog):
    """缺陷关联对话框.

    用于创建缺陷实例并绑定当前图片的检测框。
    """

    def __init__(self, parent=None, defect_classes=None, current_defects=None):
        super().__init__(parent)
        self.setWindowTitle("缺陷实例关联")
        self.setMinimumSize(520, 560)
        self.selected_defect_id = None
        self.selected_class = ""
        self.create_new = False

        layout = QVBoxLayout(self)

        # 提示
        hint = QLabel(
            "选择一个缺陷实例，将当前选中的检测框绑定到该缺陷。\n"
            "同一缺陷可跨多张相机图片绑定。"
        )
        hint.setStyleSheet("color: #666666;")
        layout.addWidget(hint)

        # 选择现有缺陷
        layout.addWidget(QLabel("选择缺陷实例:"))
        self.defect_list = QListWidget()
        self.defect_list.setMaximumHeight(240)
        if current_defects:
            for defect in current_defects:
                item = QListWidgetItem(
                    f"{defect.defect_id} | {defect.class_name}"
                )
                item.setData(Qt.ItemDataRole.UserRole, defect.defect_id)
                self.defect_list.addItem(item)
        layout.addWidget(self.defect_list)

        # 新建缺陷
        layout.addWidget(QLabel("或创建新缺陷实例:"))
        new_form = QFormLayout()
        self.class_combo = QComboBox()
        if defect_classes:
            self.class_combo.addItems(defect_classes)
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("缺陷描述（可选）")
        new_form.addRow("缺陷类别:", self.class_combo)
        new_form.addRow("描述:", self.desc_edit)
        layout.addLayout(new_form)

        # 按钮
        btn_layout = QHBoxLayout()
        bind_btn = QPushButton("绑定到选中缺陷")
        bind_btn.clicked.connect(self._on_bind_existing)
        create_bind_btn = QPushButton("创建并绑定")
        create_bind_btn.clicked.connect(self._on_create_and_bind)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addWidget(bind_btn)
        btn_layout.addWidget(create_bind_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _on_bind_existing(self):
        """绑定到现有缺陷."""
        item = self.defect_list.currentItem()
        if item is None:
            QMessageBox.warning(self, "提示", "请先选择一个缺陷实例")
            return
        self.selected_defect_id = item.data(Qt.ItemDataRole.UserRole)
        self.create_new = False
        self.accept()

    def _on_create_and_bind(self):
        """创建新缺陷并绑定."""
        cls_name = self.class_combo.currentText().strip()
        if not cls_name:
            QMessageBox.warning(self, "提示", "请选择缺陷类别")
            return
        self.selected_class = cls_name
        self.create_new = True
        self.accept()


class StatisticsDialog(QDialog):
    """统计结果展示对话框."""

    def __init__(self, parent=None, title: str = "统计分析"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 500)

        layout = QVBoxLayout(self)
        self.content = QTextEdit()
        self.content.setReadOnly(True)
        font = QFont("微软雅黑", 10)
        self.content.setFont(font)
        layout.addWidget(self.content)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def set_text(self, text: str):
        """设置文本内容."""
        self.content.setPlainText(text)


class UserDialog(QDialog):
    """设置审核人员对话框."""

    def __init__(self, parent=None, default_user: str = ""):
        super().__init__(parent)
        self.setWindowTitle("设置审核人员")
        self.setMinimumWidth(300)
        self.user_name = default_user

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.user_edit = QLineEdit(default_user)
        form.addRow("审核人员:", self.user_edit)
        layout.addLayout(form)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _on_accept(self):
        """确认."""
        name = self.user_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入审核人员姓名")
            return
        self.user_name = name
        self.accept()
