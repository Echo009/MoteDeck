"""ButtonMappingModel (QAbstractListModel bridge for the mapping
page). Mechanically split from
qt_settings_app._load_qt_classes(); only imported lazily from
there, so importing qt_settings_app never requires PySide6."""

from __future__ import annotations

from . import device_catalog
from . import key_mapping
from . import remote_layout
from . import remote_selection
from . import settings_ui
from typing import Dict, List, Optional
from .qt_settings_qml_tokens import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    Signal,
    Slot,
    _DisplayRole,
    _UserRole,
)


class ButtonMappingModel(QAbstractListModel):
    """One row per physical RC003 button (13 total, in
    remote_layout.BUTTON_ORDER - 12 ordinary HID buttons plus mic),
    exposing its identity, current mapping texts and shared selected
    state to the full-width QML mapping matrix. Hotspot roles remain for
    compatibility with older consumers of the model, but the current
    settings page uses the matrix as its sole RC003 mapping view.
    """

    ButtonIdRole = _UserRole + 1
    DisplayNameRole = _UserRole + 2
    HidUsageRole = _UserRole + 3
    ActionTextRole = _UserRole + 4
    DoubleClickTextRole = _UserRole + 5
    LongPressTextRole = _UserRole + 6
    IsMicRole = _UserRole + 7
    IsSelectedRole = _UserRole + 8
    XRole = _UserRole + 9
    YRole = _UserRole + 10
    WidthRole = _UserRole + 11
    HeightRole = _UserRole + 12
    IsVoiceRole = _UserRole + 13
    SingleNoteRole = _UserRole + 14
    DoubleNoteRole = _UserRole + 15
    LongNoteRole = _UserRole + 16
    InjectModeRole = _UserRole + 17

    # Emitted whenever a QML combo box edits a row's action text
    # (button_id, new display text) - SettingsController does not need
    # this directly (it reads the model back at save time via
    # to_display_map()), but it is kept for any future listener/test.
    actionEdited = Signal(str, str)
    mappingEdited = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._profile = device_catalog.RC003_ID
        self._initialize_rows()

    def set_profile(self, profile: str) -> None:
        if profile == self._profile:
            return
        self.beginResetModel()
        self._profile = profile
        self._initialize_rows()
        self.endResetModel()

    def _initialize_rows(self) -> None:
        self._button_ids: List[str] = list(remote_layout.button_order(self._profile))
        self._action_text: Dict[str, str] = {bid: "" for bid in self._button_ids}
        self._secondary_action_text: Dict[str, Dict[str, str]] = {
            bid: {
                key_mapping.ButtonTrigger.DOUBLE_CLICK.value: (
                    settings_ui.SECONDARY_UNCONFIGURED_DISPLAY
                ),
                key_mapping.ButtonTrigger.LONG_PRESS.value: (
                    settings_ui.SECONDARY_UNCONFIGURED_DISPLAY
                ),
            }
            for bid in self._button_ids
        }
        self._display_notes: Dict[str, Dict[str, str]] = {
            bid: {
                key_mapping.ButtonTrigger.SINGLE_CLICK.value: "",
                key_mapping.ButtonTrigger.DOUBLE_CLICK.value: "",
                key_mapping.ButtonTrigger.LONG_PRESS.value: "",
            }
            for bid in self._button_ids
        }
        self._inject_modes: Dict[str, str] = {
            bid: key_mapping.DEFAULT_INJECT_MODE for bid in self._button_ids
        }
        self._selected_button_id: str = "ok"

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008 - QML model convention
        if parent.isValid():
            return 0
        return len(self._button_ids)

    def roleNames(self):
        return {
            self.ButtonIdRole: QByteArray(b"buttonId"),
            self.DisplayNameRole: QByteArray(b"displayName"),
            self.HidUsageRole: QByteArray(b"hidUsage"),
            self.ActionTextRole: QByteArray(b"actionText"),
            self.DoubleClickTextRole: QByteArray(b"doubleClickText"),
            self.LongPressTextRole: QByteArray(b"longPressText"),
            self.IsMicRole: QByteArray(b"isMic"),
            self.IsSelectedRole: QByteArray(b"isSelected"),
            self.XRole: QByteArray(b"hotspotX"),
            self.YRole: QByteArray(b"hotspotY"),
            self.WidthRole: QByteArray(b"hotspotWidth"),
            self.HeightRole: QByteArray(b"hotspotHeight"),
            self.IsVoiceRole: QByteArray(b"isVoice"),
            self.SingleNoteRole: QByteArray(b"singleNote"),
            self.DoubleNoteRole: QByteArray(b"doubleNote"),
            self.LongNoteRole: QByteArray(b"longNote"),
            self.InjectModeRole: QByteArray(b"injectMode"),
        }

    def data(self, index, role: int = _DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._button_ids)):
            return None
        button_id = self._button_ids[index.row()]
        hotspot = remote_layout.hotspot_for(button_id, self._profile)
        if role in (self.ButtonIdRole, _DisplayRole):
            return button_id
        if role == self.DisplayNameRole:
            return remote_layout.display_names(self._profile)[button_id]
        if role == self.HidUsageRole:
            if self._profile == remote_selection.CHROMECAST_PROFILE:
                code = remote_layout.CHROMECAST_REPORT_CODES.get(button_id)
                return (
                    f"普通报告 0x{code:02X}"
                    if code is not None
                    else "ATVV 语音控制（非普通报告）"
                )
            return remote_layout.hid_usage_display(button_id)
        if role == self.ActionTextRole:
            return settings_ui.format_action_text(self._action_text[button_id])
        if role == self.DoubleClickTextRole:
            return settings_ui.format_action_text(self._secondary_action_text[button_id][
                key_mapping.ButtonTrigger.DOUBLE_CLICK.value
            ])
        if role == self.LongPressTextRole:
            return settings_ui.format_action_text(self._secondary_action_text[button_id][
                key_mapping.ButtonTrigger.LONG_PRESS.value
            ])
        if role == self.IsMicRole:
            return button_id == "mic"
        if role == self.IsSelectedRole:
            return button_id == self._selected_button_id
        if role == self.XRole:
            return hotspot.x if hotspot else 0.0
        if role == self.YRole:
            return hotspot.y if hotspot else 0.0
        if role == self.WidthRole:
            return hotspot.width if hotspot else 0.0
        if role == self.HeightRole:
            return hotspot.height if hotspot else 0.0
        if role == self.IsVoiceRole:
            return bool(hotspot and hotspot.is_voice)
        if role == self.SingleNoteRole:
            return self._display_notes[button_id][
                key_mapping.ButtonTrigger.SINGLE_CLICK.value
            ]
        if role == self.DoubleNoteRole:
            return self._display_notes[button_id][
                key_mapping.ButtonTrigger.DOUBLE_CLICK.value
            ]
        if role == self.LongNoteRole:
            return self._display_notes[button_id][
                key_mapping.ButtonTrigger.LONG_PRESS.value
            ]
        if role == self.InjectModeRole:
            return self._inject_modes[button_id]
        return None

    def load_display_map(
        self,
        display_map: Dict[str, str],
        secondary_display_map: Optional[Dict[str, Dict[str, str]]] = None,
        display_note_map: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> None:
        """Apply persisted values without rebuilding QML delegates.

        The row identity/order never changes. Emitting only the roles
        whose text changed keeps cards, photo hotspots, selected state,
        and connector canvases alive across a save/reload.
        """

        for row, button_id in enumerate(self._button_ids):
            changed_roles = []
            primary_text = display_map.get(button_id, "")
            if primary_text != self._action_text[button_id]:
                self._action_text[button_id] = primary_text
                changed_roles.append(self.ActionTextRole)
            trigger_map = (secondary_display_map or {}).get(button_id, {})
            next_secondary = {
                key_mapping.ButtonTrigger.DOUBLE_CLICK.value: trigger_map.get(
                    key_mapping.ButtonTrigger.DOUBLE_CLICK.value,
                    settings_ui.SECONDARY_UNCONFIGURED_DISPLAY,
                ),
                key_mapping.ButtonTrigger.LONG_PRESS.value: trigger_map.get(
                    key_mapping.ButtonTrigger.LONG_PRESS.value,
                    settings_ui.SECONDARY_UNCONFIGURED_DISPLAY,
                ),
            }
            current_secondary = self._secondary_action_text[button_id]
            if (
                next_secondary[key_mapping.ButtonTrigger.DOUBLE_CLICK.value]
                != current_secondary[key_mapping.ButtonTrigger.DOUBLE_CLICK.value]
            ):
                changed_roles.append(self.DoubleClickTextRole)
            if (
                next_secondary[key_mapping.ButtonTrigger.LONG_PRESS.value]
                != current_secondary[key_mapping.ButtonTrigger.LONG_PRESS.value]
            ):
                changed_roles.append(self.LongPressTextRole)
            self._secondary_action_text[button_id] = next_secondary
            raw_notes = (display_note_map or {}).get(button_id, {})
            next_notes = {
                key_mapping.ButtonTrigger.SINGLE_CLICK.value: str(
                    raw_notes.get(
                        key_mapping.ButtonTrigger.SINGLE_CLICK.value, ""
                    )
                ),
                key_mapping.ButtonTrigger.DOUBLE_CLICK.value: str(
                    raw_notes.get(
                        key_mapping.ButtonTrigger.DOUBLE_CLICK.value, ""
                    )
                ),
                key_mapping.ButtonTrigger.LONG_PRESS.value: str(
                    raw_notes.get(
                        key_mapping.ButtonTrigger.LONG_PRESS.value, ""
                    )
                ),
            }
            current_notes = self._display_notes[button_id]
            note_roles = {
                key_mapping.ButtonTrigger.SINGLE_CLICK.value: self.SingleNoteRole,
                key_mapping.ButtonTrigger.DOUBLE_CLICK.value: self.DoubleNoteRole,
                key_mapping.ButtonTrigger.LONG_PRESS.value: self.LongNoteRole,
            }
            for trigger, role in note_roles.items():
                if next_notes[trigger] != current_notes[trigger]:
                    changed_roles.append(role)
            self._display_notes[button_id] = next_notes
            if changed_roles:
                model_index = self.index(row, 0)
                self.dataChanged.emit(model_index, model_index, changed_roles)

    def to_display_map(self) -> Dict[str, str]:
        """Inverse of load_display_map() for build_save_model()."""

        return dict(self._action_text)

    def to_secondary_display_map(self) -> Dict[str, Dict[str, str]]:
        return {
            button_id: {
                trigger: (
                    ""
                    if text == settings_ui.SECONDARY_UNCONFIGURED_DISPLAY
                    else text
                )
                for trigger, text in trigger_map.items()
            }
            for button_id, trigger_map in self._secondary_action_text.items()
        }

    def to_display_note_map(self) -> Dict[str, Dict[str, str]]:
        return {
            button_id: {
                trigger: note.strip()
                for trigger, note in trigger_map.items()
                if note.strip()
            }
            for button_id, trigger_map in self._display_notes.items()
            if any(note.strip() for note in trigger_map.values())
        }

    def load_inject_modes(
        self, inject_modes: Optional[Dict[str, str]]
    ) -> None:
        """Apply persisted per-button injection backends to the rows.

        Like load_display_map() this only refreshes the roles whose value
        changed, so the QML delegates stay alive across a save/reload.
        """

        entries = inject_modes if isinstance(inject_modes, dict) else {}
        for row, button_id in enumerate(self._button_ids):
            mode = key_mapping.normalize_stored_inject_mode(
                entries.get(button_id)
            )
            if mode == self._inject_modes[button_id]:
                continue
            self._inject_modes[button_id] = mode
            model_index = self.index(row, 0)
            self.dataChanged.emit(
                model_index, model_index, [self.InjectModeRole]
            )

    def to_inject_mode_map(self) -> Dict[str, str]:
        """Inverse of load_inject_modes() for build_save_model()."""

        return dict(self._inject_modes)

    def inject_mode_for(self, button_id: str) -> str:
        return self._inject_modes.get(
            str(button_id), key_mapping.DEFAULT_INJECT_MODE
        )

    @Slot(int, str)
    def setInjectModeAt(self, row: int, mode: str) -> None:
        if not (0 <= row < len(self._button_ids)):
            return
        button_id = self._button_ids[row]
        normalized = key_mapping.normalize_stored_inject_mode(mode)
        if normalized == self._inject_modes[button_id]:
            return
        self._inject_modes[button_id] = normalized
        model_index = self.index(row, 0)
        self.dataChanged.emit(model_index, model_index, [self.InjectModeRole])
        self.mappingEdited.emit()

    def index_of(self, button_id: str) -> int:
        try:
            return self._button_ids.index(button_id)
        except ValueError:
            return -1

    @Slot(str, result=int)
    def indexOfButton(self, button_id: str) -> int:
        return self.index_of(button_id)

    @Slot(int, str)
    def setActionTextAt(self, row: int, text: str) -> None:
        if not (0 <= row < len(self._button_ids)):
            return
        button_id = self._button_ids[row]
        original = self._action_text[button_id]
        if settings_ui.action_text_matches_original(text, original):
            return
        text = settings_ui.normalize_action_text(text)
        if text == self._action_text[button_id]:
            return
        self._action_text[button_id] = text
        model_index = self.index(row, 0)
        self.dataChanged.emit(model_index, model_index, [self.ActionTextRole])
        self.actionEdited.emit(button_id, text)
        self.mappingEdited.emit()

    @Slot(int, str, str)
    def setSecondaryActionTextAt(self, row: int, trigger: str, text: str) -> None:
        if not (0 <= row < len(self._button_ids)):
            return
        if trigger not in {
            key_mapping.ButtonTrigger.DOUBLE_CLICK.value,
            key_mapping.ButtonTrigger.LONG_PRESS.value,
        }:
            return
        button_id = self._button_ids[row]
        original = self._secondary_action_text[button_id][trigger]
        if settings_ui.action_text_matches_original(text, original):
            return
        text = settings_ui.normalize_action_text(text)
        if text == self._secondary_action_text[button_id][trigger]:
            return
        self._secondary_action_text[button_id][trigger] = text
        model_index = self.index(row, 0)
        role = (
            self.DoubleClickTextRole
            if trigger == key_mapping.ButtonTrigger.DOUBLE_CLICK.value
            else self.LongPressTextRole
        )
        self.dataChanged.emit(model_index, model_index, [role])
        self.mappingEdited.emit()

    def relabel_voice_actions(
        self,
        old_labels: Dict[int, str],
        new_labels: Dict[int, str],
    ) -> None:
        """Swap renamed voice keys' display text on the button page."""

        for row, button_id in enumerate(self._button_ids):
            text = self._action_text[button_id]
            for slot, old_label in old_labels.items():
                if text != old_label:
                    continue
                new_label = new_labels.get(slot)
                if new_label and new_label != text:
                    self._action_text[button_id] = new_label
                    model_index = self.index(row, 0)
                    self.dataChanged.emit(
                        model_index, model_index, [self.ActionTextRole]
                    )
                break

    def clear_voice_action(self, slot: int, label: str = "") -> None:
        """Reset buttons bound to a deleted voice key back to 禁用."""

        changed = False
        for row, button_id in enumerate(self._button_ids):
            text = self._action_text[button_id]
            matched = settings_ui.voice_slot_for_display(text) == int(slot)
            if not matched and label and text == label:
                matched = True
            if not matched:
                continue
            self._action_text[button_id] = "禁用"
            model_index = self.index(row, 0)
            self.dataChanged.emit(model_index, model_index, [self.ActionTextRole])
            changed = True
        if changed:
            self.mappingEdited.emit()

    @Slot(int, str, str)
    def setDisplayNoteAt(self, row: int, trigger: str, text: str) -> None:
        if not (0 <= row < len(self._button_ids)):
            return
        valid_roles = {
            key_mapping.ButtonTrigger.SINGLE_CLICK.value: self.SingleNoteRole,
            key_mapping.ButtonTrigger.DOUBLE_CLICK.value: self.DoubleNoteRole,
            key_mapping.ButtonTrigger.LONG_PRESS.value: self.LongNoteRole,
        }
        if trigger not in valid_roles:
            return
        button_id = self._button_ids[row]
        clean_text = str(text).strip()
        if clean_text == self._display_notes[button_id][trigger]:
            return
        self._display_notes[button_id][trigger] = clean_text
        model_index = self.index(row, 0)
        self.dataChanged.emit(
            model_index, model_index, [valid_roles[trigger]]
        )
        self.mappingEdited.emit()

    def set_selected_button(self, button_id: str) -> None:
        if button_id == self._selected_button_id or button_id not in self._action_text:
            return
        old_row = self.index_of(self._selected_button_id)
        self._selected_button_id = button_id
        new_row = self.index_of(button_id)
        for row in (old_row, new_row):
            if row >= 0:
                model_index = self.index(row, 0)
                self.dataChanged.emit(model_index, model_index, [self.IsSelectedRole])

    def selected_button_id(self) -> str:
        return self._selected_button_id
