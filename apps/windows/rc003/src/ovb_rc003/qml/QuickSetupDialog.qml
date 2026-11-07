// 「快速配置」：把常用语音应用的接入步骤列出来，点某一行的「配置」展开时间轴。
// 微信输入法这一项已接后端：检测安装、创建语音键并录制快捷键；其余仍是界面占位。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import OvbRc003Settings 1.0

SettingsDialog {
    id: root
    objectName: "quickSetupDialog"
    title: qsTr("快速配置")
    titleNote: qsTr("选择要接入的语音应用，按步骤完成配置。")
    preferredWidth: 560
    standardButtons: Dialog.NoButton

    // 图标块：有原版图形标（mark）就放图，否则用线条图标（icon）。
    readonly property int iconSize: 28
    readonly property int iconGap: 10
    // 步骤文字与上方应用名左侧对齐：都从图标块右侧这道线起排。
    readonly property int stepTextIndent: iconSize + iconGap

    // 微信输入法：装没装→建语音键（录一次微信输入法的语音快捷键）→去微信输入法里开全局生效。
    function wetypeSteps() {
        const hotkeyText = SettingsController.wetypeVoiceKeyHotkeyText
        return [
            {
                text: SettingsController.wetypeInstalled
                    ? qsTr("检测微信输入法是否已安装")
                    : qsTr("点击访问官网下载安装软件"),
                done: SettingsController.wetypeInstalled,
                action: "openWetypeWebsite"
            },
            {
                text: hotkeyText
                    ? qsTr("微信输入法语音键已创建（%1）").arg(hotkeyText)
                    : qsTr("点击创建微信输入法语音键，并按下微信输入法的语音快捷键"),
                done: hotkeyText !== "",
                action: "wetypeVoiceKey"
            },
            {
                text: qsTr("去微信输入法里开启“快捷键全局生效”，并取消勾选“启动语音输入”，仅保留“按住说话”，并把麦克风设置为 CABLE Output，注意快捷键要和刚才设置的快捷键一致"),
                done: false,
                // 这一步要用户自己去微信输入法里设置，程序检测不到；前两步做完
                // 后用感叹号提示该去手动完成了。
                manual: SettingsController.wetypeInstalled && hotkeyText !== ""
            }
        ]
    }

    // 豆包输入法：装没装→装驱动级注入→建语音键（注入改成驱动级）→去豆包输入法里手动设置。
    function doubaoSteps() {
        const hotkeyText = SettingsController.doubaoVoiceKeyHotkeyText
        const driverReady = SettingsController.inputDriverInstalled
        return [
            {
                text: SettingsController.doubaoInstalled
                    ? qsTr("检测豆包输入法是否已安装")
                    : qsTr("点击访问官网下载安装软件"),
                done: SettingsController.doubaoInstalled,
                action: "openDoubaoWebsite"
            },
            {
                text: driverReady
                    ? qsTr("驱动级按键注入已安装")
                    : qsTr("点击安装驱动"),
                done: driverReady,
                action: "installInputDriver"
            },
            {
                text: hotkeyText
                    ? qsTr("豆包输入法语音键已创建（%1）").arg(hotkeyText)
                    : qsTr("点击创建豆包输入法语音键，并按下豆包输入法的语音快捷键"),
                done: hotkeyText !== "",
                action: "doubaoVoiceKey"
            },
            {
                text: qsTr("去豆包输入法里禁用免按模式（在免按模式快捷键里点错叉），开启全局唤起语音，并把麦克风设置为 CABLE Output，注意快捷键要和刚才设置的快捷键一致"),
                done: false,
                // 这一步要用户自己去豆包输入法里设置，程序检测不到；前三步做完
                // 后用感叹号提示该去手动完成了。
                manual: SettingsController.doubaoInstalled && driverReady
                    && hotkeyText !== ""
            }
        ]
    }

    // Chatterfly：装没装→装驱动级注入→依次建三个语音键（注入改成驱动级、打开延迟发送）
    // →去 Chatterfly 里手动设置。
    function chatterflySteps() {
        const labels = [qsTr("语音输入"), qsTr("指令模式"), qsTr("翻译")]
        const hotkeyTexts = SettingsController.chatterflyVoiceKeyHotkeyTexts
        const driverReady = SettingsController.inputDriverInstalled
        const steps = [
            {
                text: SettingsController.chatterflyInstalled
                    ? qsTr("检测 Chatterfly 是否已安装")
                    : qsTr("点击访问官网下载安装软件"),
                done: SettingsController.chatterflyInstalled,
                action: "openChatterflyWebsite"
            },
            {
                text: driverReady
                    ? qsTr("驱动级按键注入已安装")
                    : qsTr("点击安装驱动"),
                done: driverReady,
                action: "installInputDriver"
            }
        ]
        for (let i = 0; i < labels.length; ++i) {
            const hotkeyText = hotkeyTexts[i] || ""
            steps.push({
                text: hotkeyText
                    ? qsTr("%1语音键已创建（%2）").arg("Chatterfly" + labels[i]).arg(hotkeyText)
                    : qsTr("点击创建 %1 语音键，并按下它在 Chatterfly 里的语音快捷键").arg("Chatterfly" + labels[i]),
                done: hotkeyText !== "",
                action: "chatterflyVoiceKey",
                actionIndex: i
            })
        }
        steps.push({
            text: qsTr("去Chatterfly里开启快捷键全局可用，并把麦克风设置为 CABLE Output，注意快捷键要和刚才设置的快捷键一致"),
            done: false,
            // 这一步要用户自己去 Chatterfly 里设置，程序检测不到；前五步做完
            // 后用感叹号提示该去手动完成了。
            manual: SettingsController.chatterflyInstalled && driverReady
                && hotkeyTexts.length === 3
                && hotkeyTexts[0] !== "" && hotkeyTexts[1] !== "" && hotkeyTexts[2] !== ""
        })
        return steps
    }

    // OpenMexia：装没装→下载语音模型→开启连接。
    function openmexiaSteps() {
        const installed = SettingsController.openMexiaInstalled
        const modelReady = SettingsController.asrModelReady
        const modelBusy = SettingsController.asrModelBusy
        const connected = SettingsController.openMexiaConnected
        return [
            {
                text: installed
                    ? qsTr("OpenMexia 已安装")
                    : qsTr("点击访问官网下载安装软件"),
                done: installed,
                action: "openOpenMexiaWebsite"
            },
            {
                text: modelReady
                    ? qsTr("语音识别模型已下载")
                    : modelBusy
                        ? qsTr("正在下载语音识别模型…")
                        : qsTr("点击下载语音模型（约 228MB）"),
                done: modelReady,
                action: "installAsrModel"
            },
            {
                text: connected
                    ? qsTr("OpenMexia 已连接")
                    : qsTr("点击开启连接"),
                done: connected,
                action: "connectOpenMexia"
            }
        ]
    }

    // Vokie：装没装→下载插件→用户自己导入插件→开启连接。
    property bool vokiePluginDownloaded: false

    function vokieSteps() {
        const installed = SettingsController.vokieInstalled
        const downloaded = root.vokiePluginDownloaded
        const connected = SettingsController.voicePluginConnected
        return [
            {
                text: installed
                    ? qsTr("Vokie 已安装")
                    : qsTr("点击访问官网下载安装软件"),
                done: installed,
                action: "openVokieWebsite"
            },
            {
                // 开始下载只能说明打开了下载链接，不能确认用户已经下载完，
                // 所以这一步一直可点、不计入进度，用感叹号提示用户去完成。
                text: qsTr("点击下载插件（最新版 MoteDeck2Vokie）"),
                done: false,
                manual: true,
                action: "downloadVokiePlugin"
            },
            {
                text: qsTr("解压缩插件并放在不包含中文的目录，打开 Vokie，点击“账户与设置 > 设备实验室 > 添加更多设备 > 选择插件文件夹”，在文件浏览器中选择刚才的插件文件夹导入插件"),
                done: false,
                // 这一步要用户自己去 Vokie 里导入插件，程序检测不到；点过下载插件
                // 后用感叹号提示该去手动完成了。
                manual: installed && downloaded
            },
            {
                text: connected
                    ? qsTr("Vokie 已连接")
                    : qsTr("点击开启连接"),
                done: connected,
                action: "connectVokie"
            }
        ]
    }

    // 后端接入后换成真实数据；每项形如 { name: "", mark, markInset, steps: [{ text: "", done: false }] }
    property var setupTargets: [
        {
            name: qsTr("微信输入法"),
            mark: Qt.resolvedUrl(root.tokens.darkMode ? "assets/wetype-dark.png" : "assets/wetype.png"),
            steps: wetypeSteps()
        },
        {
            name: qsTr("豆包输入法"),
            mark: Qt.resolvedUrl(root.tokens.darkMode ? "assets/doubao-dark.png" : "assets/doubao.png"),
            markBackground: root.tokens.darkMode ? "#FFFFFF" : "#141414",
            steps: doubaoSteps()
        },
        {
            name: qsTr("Chatterfly"),
            mark: Qt.resolvedUrl(root.tokens.darkMode ? "assets/chatterfly-dark.png" : "assets/chatterfly.png"),
            steps: chatterflySteps()
        },
        {
            name: qsTr("OpenMexia（米家控制）"),
            mark: Qt.resolvedUrl(root.tokens.darkMode ? "assets/openmexia-mark-dark.png" : "assets/openmexia-mark.svg"),
            markInset: 5,
            steps: openmexiaSteps()
        },
        {
            name: qsTr("Vokie"),
            mark: Qt.resolvedUrl(root.tokens.darkMode ? "assets/vokie-mark-dark.png" : "assets/vokie-mark.svg"),
            markInset: 5,
            steps: vokieSteps()
        }
    ]
    // 同一时间只展开一行；-1 表示全部收起。
    property int expandedIndex: -1

    function toggleRow(index) {
        expandedIndex = expandedIndex === index ? -1 : index
    }

    // 需要用户自己去应用里完成的步骤（manual）不计入「x/y 步」，
    // 否则程序检测不到它们，计数永远到不了满。
    function totalStepCount(steps) {
        let total = 0
        for (let i = 0; i < steps.length; ++i) {
            if (!steps[i].manual)
                total += 1
        }
        return total
    }

    function completedCount(steps) {
        let done = 0
        for (let i = 0; i < steps.length; ++i) {
            if (steps[i].done && !steps[i].manual)
                done += 1
        }
        return done
    }

    // 第 2 步：先录一次微信输入法的语音快捷键，再据此创建语音键。
    function startWetypeVoiceKey() {
        wetypeRecorder.openRecorder()
    }

    // 豆包输入法同理，只是建好后会把麦克风键的注入方式切成已装的驱动。
    function startDoubaoVoiceKey() {
        doubaoRecorder.openRecorder()
    }

    // Chatterfly 的三个语音键共用一次录制，用下标区分是哪一个。
    property int chatterflyVoiceKeyIndex: 0

    function startChatterflyVoiceKey(index) {
        chatterflyVoiceKeyIndex = index
        chatterflyRecorder.openRecorder()
    }

    // 豆包第 2 步：没装驱动时点一下，走既有的 WinUHid 安装流程。
    function installInputDriver() {
        driverInstallConfirmDialog.open()
    }

    property string driverInstallMessage: ""

    onOpened: {
        expandedIndex = -1
        SettingsController.refreshQuickSetup()
    }

    // 录制微信输入法的语音快捷键；取到和弦后写入语音键配置。
    ShortcutRecorderDialog {
        id: wetypeRecorder
        objectName: "wetypeVoiceKeyRecorder"
        tokens: root.tokens
        onChordAccepted: function(chord) {
            SettingsController.createWetypeVoiceKey(chord)
        }
    }

    // 录制豆包输入法的语音快捷键。
    ShortcutRecorderDialog {
        id: doubaoRecorder
        objectName: "doubaoVoiceKeyRecorder"
        tokens: root.tokens
        onChordAccepted: function(chord) {
            SettingsController.createDoubaoVoiceKey(chord)
        }
    }

    // 录制 Chatterfly 里某一个语音功能的快捷键。
    ShortcutRecorderDialog {
        id: chatterflyRecorder
        objectName: "chatterflyVoiceKeyRecorder"
        tokens: root.tokens
        onChordAccepted: function(chord) {
            SettingsController.createChatterflyVoiceKey(root.chatterflyVoiceKeyIndex, chord)
        }
    }

    SettingsDialog {
        id: driverInstallConfirmDialog
        tokens: root.tokens
        preferredWidth: 340 + root.tokens.dialogPadding * 2
        objectName: "quickSetupDriverInstallDialog"
        title: qsTr("安装驱动？")
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: {
            const result = SettingsController.installWinUHidDriver()
            root.driverInstallMessage = result.message
            SettingsController.refreshQuickSetup()
            driverInstallResultDialog.open()
        }

        UiLabel {
            tokens: root.tokens
            kind: bodyKind
            width: 340
            wrapMode: Text.WordWrap
            text: qsTr("安装需要管理员权限，软件只会启动随包附带的安装脚本，绝不会静默安装。确定现在安装吗？")
        }
    }

    SettingsDialog {
        id: driverInstallResultDialog
        tokens: root.tokens
        preferredWidth: 340 + root.tokens.dialogPadding * 2
        objectName: "quickSetupDriverInstallResultDialog"
        title: qsTr("安装结果")
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Ok

        UiLabel {
            tokens: root.tokens
            kind: bodyKind
            width: 340
            wrapMode: Text.WordWrap
            text: root.driverInstallMessage
        }
    }

    contentItem: ColumnLayout {
        spacing: 0

        ScrollView {
            id: setupScroll
            objectName: "quickSetupList"
            Layout.fillWidth: true
            // 高度跟着内容走，展开才长高；超过上限再滚动。
            Layout.preferredHeight: Math.min(setupList.implicitHeight, 420)
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                id: setupList
                width: setupScroll.availableWidth
                spacing: root.tokens.spacingSmall

                Repeater {
                    model: root.setupTargets

                    delegate: Rectangle {
                        id: setupRow
                        required property var modelData
                        required property int index
                        readonly property bool expanded: root.expandedIndex === index

                        objectName: "quickSetupRow_" + index
                        Layout.fillWidth: true
                        implicitHeight: setupRowHeader.height
                            + (setupRow.expanded ? setupTimeline.implicitHeight : 0)
                        radius: root.tokens.cornerRadiusControl
                        // 收起时整块浮上变灰提示可点；展开后只有时间轴每一项单独有热区。
                        color: !setupRow.expanded && setupRowHover.hovered
                            ? root.tokens.surfaceMuted : root.tokens.surface
                        border.width: root.tokens.hairlineWidth
                        border.color: setupRow.expanded
                            ? root.tokens.borderStrong : root.tokens.cardBorder
                        clip: true

                        HoverHandler { id: setupRowHover }

                        Behavior on implicitHeight {
                            NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
                        }

                        Item {
                            id: setupRowHeader
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: 52

                            // 应用图标：官方图标直接铺满小块；Vokie/OpenMexia 的白线条标留内边距。
                            Rectangle {
                                id: setupRowIcon
                                anchors.left: parent.left
                                anchors.leftMargin: root.tokens.spacingMedium
                                anchors.verticalCenter: parent.verticalCenter
                                width: root.iconSize
                                height: root.iconSize
                                radius: root.tokens.cornerRadiusSmall
                                color: setupRow.modelData.markBackground || (root.tokens.darkMode ? "#EBEBEB" : "#141414")
                                clip: true

                                Image {
                                    anchors.fill: parent
                                    anchors.margins: setupRow.modelData.markInset || 0
                                    visible: !!setupRow.modelData.mark
                                    source: setupRow.modelData.mark || ""
                                    sourceSize.width: root.iconSize * 2
                                    sourceSize.height: root.iconSize * 2
                                    smooth: true
                                    fillMode: Image.PreserveAspectFit
                                }
                            }

                            Column {
                                id: setupRowLabels
                                anchors.left: setupRowIcon.right
                                anchors.leftMargin: root.iconGap
                                anchors.right: parent.right
                                anchors.rightMargin: root.tokens.spacingMedium
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2

                                UiLabel {
                                    objectName: "quickSetupRowName_" + setupRow.index
                                    width: parent.width
                                    tokens: root.tokens
                                    kind: bodyKind
                                    text: setupRow.modelData.name
                                    elide: Text.ElideRight
                                }
                                UiLabel {
                                    width: parent.width
                                    tokens: root.tokens
                                    kind: noteKind
                                    text: qsTr("%1/%2 步")
                                        .arg(root.completedCount(setupRow.modelData.steps))
                                        .arg(root.totalStepCount(setupRow.modelData.steps))
                                }
                            }

                            // 整行头都是点击区：点一下展开，再点一下收起。
                            MouseArea {
                                objectName: "quickSetupRowToggle_" + setupRow.index
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                Accessible.name: setupRow.modelData.name
                                onClicked: root.toggleRow(setupRow.index)
                            }
                        }

                        Item {
                            id: setupTimeline
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: setupRowHeader.bottom
                            anchors.leftMargin: root.tokens.spacingMedium
                            anchors.rightMargin: root.tokens.spacingMedium
                            implicitHeight: setupSteps.implicitHeight
                                + root.tokens.spacingMedium

                            Column {
                                id: setupSteps
                                width: parent.width

                                Repeater {
                                    model: setupRow.modelData.steps

                                    delegate: Item {
                                        id: setupStep

                                        required property var modelData
                                        required property int index
                                        readonly property bool last:
                                            index === setupRow.modelData.steps.length - 1
                                        // 需要用户手动完成、且前序步骤已就绪：圆点显示感叹号。
                                        readonly property bool manualPending:
                                            !!modelData.manual && !modelData.done
                                        // 还没做完的带动作步骤都可点：装驱动、打开官网、
                                        // 下载模型/插件、开启连接。
                                        readonly property bool actionPending:
                                            !!modelData.action && !modelData.done

                                        width: setupSteps.width
                                        // 文字放不下就换行，步高跟着文字长。
                                        height: Math.max(34,
                                            setupStepText.implicitHeight + 12)

                                        HoverHandler { id: setupStepHover }

                                        // 每一项自己的悬停热区。
                                        Rectangle {
                                            anchors.fill: parent
                                            radius: root.tokens.cornerRadiusSmall
                                            color: setupStepHover.hovered
                                                ? root.tokens.hover : "transparent"
                                        }

                                        // 时间轴连线：分两段画，行与行之间就不会因为该行
                                        // 高度不同（文字换行）而断开。
                                        // 上段：行首连到本行圆点上方。
                                        Rectangle {
                                            x: 14 - width / 2
                                            y: 0
                                            width: root.tokens.hairlineWidth
                                            height: setupStep.index > 0
                                                ? setupStep.height / 2 - 8 : 0
                                            visible: setupStep.index > 0
                                            color: root.tokens.border
                                        }
                                        // 下段：本行圆点下方连到行尾，接下一行的上段。
                                        Rectangle {
                                            x: 14 - width / 2
                                            y: setupStep.height / 2 + 8
                                            width: root.tokens.hairlineWidth
                                            height: setupStep.last ? 0
                                                : setupStep.height / 2 - 8
                                            visible: !setupStep.last
                                            color: root.tokens.border
                                        }

                                        // 圆点：做过的步骤显示对勾；需手动完成的步骤显示感叹号。
                                        // 中点对齐上方图标块的竖直中线。
                                        Rectangle {
                                            x: 6
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: 16
                                            height: 16
                                            radius: width / 2
                                            color: setupStep.modelData.done || setupStep.manualPending
                                                ? root.tokens.accent : "transparent"
                                            border.width: root.tokens.hairlineWidth
                                            border.color: setupStep.modelData.done || setupStep.manualPending
                                                ? root.tokens.accent : root.tokens.borderStrong

                                            SvgIcon {
                                                anchors.centerIn: parent
                                                visible: setupStep.modelData.done
                                                name: "check"
                                                size: 10
                                                color: root.tokens.accentText
                                            }

                                            Text {
                                                anchors.centerIn: parent
                                                visible: setupStep.manualPending
                                                text: "!"
                                                font.pixelSize: 11
                                                font.bold: true
                                                color: root.tokens.accentText
                                            }
                                        }

                                        UiLabel {
                                            id: setupStepText
                                            anchors.left: parent.left
                                            anchors.leftMargin: root.stepTextIndent
                                            anchors.right: parent.right
                                            anchors.verticalCenter: parent.verticalCenter
                                            tokens: root.tokens
                                            kind: bodyKind
                                            text: setupStep.modelData.text
                                            wrapMode: Text.WordWrap
                                            color: setupStep.modelData.done
                                                ? root.tokens.textTertiary : root.tokens.textPrimary
                                        }

                                        // 带 action 的步骤可点；语音键建好以后还能重录。
                                        MouseArea {
                                            anchors.fill: parent
                                            visible: setupStep.modelData.action === "wetypeVoiceKey"
                                                || setupStep.modelData.action === "doubaoVoiceKey"
                                                || setupStep.modelData.action === "chatterflyVoiceKey"
                                                || setupStep.actionPending
                                            enabled: visible
                                            cursorShape: Qt.PointingHandCursor
                                            onClicked: {
                                                const action = setupStep.modelData.action
                                                if (action === "wetypeVoiceKey")
                                                    root.startWetypeVoiceKey()
                                                else if (action === "doubaoVoiceKey")
                                                    root.startDoubaoVoiceKey()
                                                else if (action === "chatterflyVoiceKey")
                                                    root.startChatterflyVoiceKey(setupStep.modelData.actionIndex)
                                                else if (action === "installInputDriver")
                                                    root.installInputDriver()
                                                else if (action === "openOpenMexiaWebsite")
                                                    SettingsController.openOpenMexiaWebsite()
                                                else if (action === "openWetypeWebsite")
                                                    SettingsController.openWetypeWebsite()
                                                else if (action === "openDoubaoWebsite")
                                                    SettingsController.openDoubaoWebsite()
                                                else if (action === "openChatterflyWebsite")
                                                    SettingsController.openChatterflyWebsite()
                                                else if (action === "installAsrModel")
                                                    SettingsController.installAsrModel()
                                                else if (action === "connectOpenMexia")
                                                    SettingsController.connectOpenMexia()
                                                else if (action === "openVokieWebsite")
                                                    SettingsController.openVokieWebsite()
                                                else if (action === "downloadVokiePlugin") {
                                                    if (SettingsController.openVokiePluginDownload())
                                                        root.vokiePluginDownloaded = true
                                                }
                                                else if (action === "connectVokie")
                                                    SettingsController.connectVoicePlugin()
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // 底栏：虚拟声卡（VB-CABLE）没装时提示先安装并重启。
        Rectangle {
            Layout.fillWidth: true
            Layout.topMargin: root.tokens.spacingMedium
            Layout.preferredHeight: root.tokens.hairlineWidth
            color: root.tokens.border
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: root.tokens.spacingMedium
            visible: !SettingsController.vbCableInstalled
            spacing: root.tokens.spacingMedium

            UiLabel {
                tokens: root.tokens
                kind: bodyKind
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: qsTr("未检测到虚拟声卡（VB-CABLE），要先安装虚拟声卡并重启电脑（如果只用 Vokie 和 OpenMexia，不需要安装虚拟声卡）。")
            }

            CompactButton {
                tokens: root.tokens
                text: qsTr("安装虚拟声卡")
                onClicked: DiagnosticsController.launchVbCableSetup()
            }
        }

        UiLabel {
            Layout.fillWidth: true
            Layout.topMargin: SettingsController.vbCableInstalled
                ? root.tokens.spacingMedium : root.tokens.spacingSmall
            tokens: root.tokens
            kind: noteKind
            wrapMode: Text.WordWrap
            text: qsTr("所有语音键均可在「语音 > 语音键配置」中统一管理，支持删除、重命名、重映射、更换麦克风以及调整顺序。修改后立即生效，无需重新创建，也不影响其他已配置的按键。")
        }
    }
}
