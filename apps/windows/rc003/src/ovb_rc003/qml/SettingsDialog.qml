import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: root
    property var tokens
    property real preferredWidth: 480
    property string titleNote: ""
    // 标题栏右侧的问号帮助：非空时显示图标，指针停在上面就展开这段说明。
    property string helpText: ""
    property string closeButtonObjectName: ""
    property bool dismissalEnabled: true

    parent: Overlay.overlay
    modal: true
    popupType: Popup.Item
    anchors.centerIn: parent
    width: Math.min(preferredWidth, parent.width - 32)
    // 版心：标题、内容、底部按钮左右统一卡在 tokens.dialogPadding。
    padding: root.tokens.dialogPadding
    topPadding: 0
    leftInset: 0
    rightInset: 0
    topInset: 0
    bottomInset: 0
    standardButtons: Dialog.NoButton
    closePolicy: dismissalEnabled ? Popup.CloseOnEscape : Popup.NoAutoClose

    background: Rectangle {
        radius: root.tokens.cornerRadiusLarge
        color: root.tokens.surface
        border.width: root.tokens.hairlineWidth
        border.color: root.tokens.border
    }

    header: Item {
        implicitHeight: root.tokens.dialogTopPadding
            + root.tokens.dialogTitleHeight + root.tokens.dialogHeaderGap
        RowLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.topMargin: root.tokens.dialogTopPadding
            height: root.tokens.dialogTitleHeight
            anchors.leftMargin: root.leftPadding
            anchors.rightMargin: root.rightPadding - root.tokens.dialogCloseButtonOutset
            spacing: root.tokens.spacingLarge
            UiLabel {
                tokens: root.tokens
                kind: sectionTitleKind
                text: root.title
                font.pixelSize: root.tokens.fontSizeTitle
                font.weight: Font.Medium
            }
            UiLabel {
                id: note
                tokens: root.tokens
                kind: noteKind
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: root.titleNote
                textFormat: Text.PlainText
                elide: Text.ElideRight
                HoverHandler { id: noteHover }
                CompactToolTip {
                    tokens: root.tokens
                    active: noteHover.hovered && note.truncated
                    text: root.titleNote
                }
            }
            Item {
                id: helpItem
                objectName: "settingsDialogHelpIcon"
                visible: root.helpText.length > 0
                implicitWidth: 16
                implicitHeight: 16
                Layout.alignment: Qt.AlignVCenter

                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: "transparent"
                    border.width: root.tokens.hairlineWidth
                    border.color: helpHover.hovered
                        ? root.tokens.textPrimary : root.tokens.border
                }
                Text {
                    anchors.centerIn: parent
                    text: "?"
                    color: helpHover.hovered
                        ? root.tokens.textPrimary : root.tokens.textSecondary
                    font.family: root.tokens.fontFamily
                    font.pixelSize: root.tokens.fontSizeSmall
                    font.weight: Font.Medium
                }
                HoverHandler { id: helpHover }
                CompactToolTip {
                    tokens: root.tokens
                    persistent: true
                    maximumTextWidth: 320
                    // 贴着问号向下展开，右边缘与问号对齐。
                    x: helpItem.width - width
                    y: helpItem.height + root.tokens.spacingSmall
                    active: helpHover.hovered
                    text: root.helpText
                }
            }
            DialogCloseButton {
                objectName: root.closeButtonObjectName
                tokens: root.tokens
                enabled: root.dismissalEnabled
                onCloseRequested: root.reject()
            }
        }
    }

    footer: DialogButtonBox {
        id: buttons
        visible: root.standardButtons !== Dialog.NoButton
        standardButtons: root.standardButtons
        alignment: Qt.AlignRight
        spacing: root.tokens.spacingSmall
        leftPadding: root.leftPadding
        rightPadding: root.rightPadding
        topPadding: root.tokens.dialogFooterGap
        bottomPadding: root.bottomPadding
        background: Item {}
        function translateButtons() {
            const ok = standardButton(Dialog.Ok)
            const cancel = standardButton(Dialog.Cancel)
            if (ok) ok.text = qsTr("确定")
            if (cancel) cancel.text = qsTr("取消")
        }
        Component.onCompleted: translateButtons()
        onStandardButtonsChanged: Qt.callLater(translateButtons)
        delegate: CompactButton {
            tokens: root.tokens
            compactMinimumWidth: root.tokens.buttonWidth4Chars
        }
    }
}
