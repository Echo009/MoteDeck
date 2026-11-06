// 语音键的「TSF 切换」：选一个输入法，按下这条语音键前先切过去再注入快捷键。
// 部分输入法只有成为当前 TSF 才会响应语音，所以需要这一层选择。
// SettingsController is a QML singleton - see main.qml.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import OvbRc003Settings 1.0

SettingsDialog {
    id: root
    objectName: "voiceTsfMethodDialog"
    title: qsTr("选择输入法")
    titleNote: qsTr("按下这条语音键时先切换到所选输入法。")
    preferredWidth: 460
    closeButtonObjectName: "voiceTsfMethodCloseButton"
    standardButtons: Dialog.Ok | Dialog.Cancel
    // 空字符串代表「不启用」：按下语音键时不切换输入法。
    property string selectedProfile: ""
    // 系统自带输入法默认不列出来，勾选左下角复选框才显示。
    property bool showBuiltin: false
    property var allMethods: []
    readonly property var methods: {
        const items = [{ "id": "", "name": qsTr("不启用（保持当前输入法）"),
                           "language": "", "builtin": false }]
        for (let i = 0; i < allMethods.length; ++i) {
            const row = allMethods[i]
            if (!showBuiltin && row.builtin)
                continue
            items.push(row)
        }
        return items
    }
    signal profileSelected(string profile)

    function choose(profileId) {
        selectedProfile = String(profileId || "")
    }

    onAboutToShow: {
        showBuiltin = false
        const rows = SettingsController.tsfInputMethods()
        const items = []
        for (let i = 0; i < rows.length; ++i) {
            items.push({
                "id": String(rows[i].id || ""),
                "name": String(rows[i].name || ""),
                "language": String(rows[i].language || ""),
                "builtin": !!rows[i].builtin
            })
        }
        allMethods = items
    }
    onAccepted: root.profileSelected(root.selectedProfile)

    contentItem: ColumnLayout {
        spacing: root.tokens.spacingSmall

        ScrollView {
            id: methodList
            objectName: "voiceTsfMethodList"
            Layout.fillWidth: true
            Layout.preferredHeight: 240
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                objectName: "voiceTsfMethodListContent"
                width: methodList.availableWidth
                spacing: 2
                Repeater {
                    model: root.methods
                    delegate: Rectangle {
                        id: methodRow
                        required property var modelData
                        required property int index
                        readonly property bool checked:
                            root.selectedProfile === String(modelData.id)

                        objectName: "voiceTsfMethodRow_" + index
                        Layout.fillWidth: true
                        implicitHeight: 36
                        radius: root.tokens.cornerRadiusControl
                        color: checked ? root.tokens.accentSoft
                            : methodRowHover.hovered
                                ? root.tokens.buttonHover : "transparent"
                        border.width: checked
                            ? root.tokens.structuralDividerWidth : 0
                        border.color: root.tokens.accent
                        Accessible.name: modelData.name

                        HoverHandler { id: methodRowHover }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: root.choose(methodRow.modelData.id)
                        }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            spacing: root.tokens.spacingSmall
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.minimumWidth: 0
                                spacing: 0
                                UiLabel {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    tokens: root.tokens
                                    kind: bodyKind
                                    text: methodRow.modelData.name
                                    elide: Text.ElideRight
                                }
                                UiLabel {
                                    Layout.fillWidth: true
                                    Layout.minimumWidth: 0
                                    tokens: root.tokens
                                    kind: noteKind
                                    visible: String(methodRow.modelData.language).length > 0
                                    text: methodRow.modelData.language
                                    elide: Text.ElideRight
                                }
                            }
                            SvgIcon {
                                Layout.alignment: Qt.AlignVCenter
                                visible: methodRow.checked
                                name: "check"
                                size: 16
                                color: root.tokens.accent
                            }
                        }
                    }
                }
            }
        }

        // 左下角：勾选后才把系统自带的输入法也列出来。
        // 方框按文字基线对齐，避免行高把上下位置带偏。
        Rectangle {
            id: showBuiltinCheck
            objectName: "voiceTsfShowBuiltinCheck"
            Layout.alignment: Qt.AlignLeft
            implicitWidth: showBuiltinRow.implicitWidth + 12
            implicitHeight: showBuiltinRow.implicitHeight + 8
            radius: root.tokens.cornerRadiusControl
            color: showBuiltinHover.hovered ? root.tokens.buttonHover : "transparent"

            RowLayout {
                id: showBuiltinRow
                anchors.centerIn: parent
                width: implicitWidth
                height: implicitHeight
                spacing: 6

                Rectangle {
                    Layout.alignment: Qt.AlignBaseline
                    baselineOffset: implicitHeight - 3
                    implicitWidth: 14
                    implicitHeight: 14
                    radius: 3
                    color: root.showBuiltin ? root.tokens.accent : "transparent"
                    border.width: root.showBuiltin ? 0 : 1
                    border.color: root.tokens.borderStrong

                    SvgIcon {
                        anchors.centerIn: parent
                        visible: root.showBuiltin
                        name: "check"
                        size: 10
                        color: root.tokens.accentText
                    }
                }

                UiLabel {
                    Layout.alignment: Qt.AlignBaseline
                    tokens: root.tokens
                    kind: noteKind
                    text: qsTr("显示系统自带输入法")
                }
            }

            HoverHandler {
                id: showBuiltinHover
                cursorShape: Qt.PointingHandCursor
            }
            TapHandler {
                onTapped: root.showBuiltin = !root.showBuiltin
            }
        }
    }
}
