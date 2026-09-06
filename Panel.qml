import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// You've Got Mail: unread only. Click a Gmail row to preview it in place.
//
// Data comes from `bin/you-got-mail`. The script talks to a provider; this
// file only draws the pile and opens the URL the provider already built.
// No token is handled here.
//
// Every string below the header comes from a mail someone else wrote, so each
// Text carries `textFormat: Text.PlainText`.
Panel {
  id: root

  moduleName: "bvisagie.you-got-mail"
  ipcTarget: "bvisagie.you-got-mail"
  manageIpc: false

  readonly property string script:
    Qt.resolvedUrl("bin/you-got-mail").toString().replace(/^file:\/\//, "")

  readonly property string iconExternal: "\uF08E"
  readonly property string iconMarkAll: "\uF2B6"
  readonly property string iconConfirm: "\uF00C"
  readonly property string iconPrev: "\uF053"
  readonly property string iconNext: "\uF054"
  readonly property string iconBack: "\uF060"
  readonly property string iconImages: "\uF03E"

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color accent: Color.accent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property var messages: []
  property int unread: 0
  property string email: ""
  property string searchUrl: ""
  property var inboxes: []
  property bool reachable: true
  property string errorText: ""
  property string warningText: ""
  property string pendingId: ""
  property var readQueue: []
  property var dismissedIds: ({})
  property bool markAllArmed: false
  property bool markAllBusy: false
  property string actionWarning: ""
  property int cursor: -1

  property bool detailOpen: false
  property bool detailBusy: false
  property var detailMessage: null
  property string detailError: ""
  property string detailContentUrl: "about:blank"
  property string previewRequestedId: ""
  property bool remoteContentAllowed: false
  property int previewRetriesRemaining: 0

  property string pageToken: ""
  property var pageStack: []
  property string nextPage: ""
  property int accountCount: 0
  readonly property bool hasPrev: pageStack.length > 0
  readonly property bool hasNext: nextPage !== ""

  property double now: 0

  readonly property int badgeCount: unread
  readonly property bool hasUnread: unread > 0

  readonly property int badgeWidth: badgeCount > 0
    ? Math.max(Style.space(12), String(badgeCount).length * Style.space(6) + Style.space(8))
    : 0
  readonly property int barContentWidth: Style.bar.iconFont + badgeWidth + Style.space(5)
  readonly property int barSlot: barContentWidth + Style.space(10)

  implicitWidth: bar && bar.vertical ? (bar ? bar.barSize : Style.bar.sizeHorizontal) : barSlot
  implicitHeight: bar && bar.vertical ? barSlot : (bar ? bar.barSize : Style.bar.sizeHorizontal)

  function validToken(t) {
    return /^[A-Za-z0-9_-]{1,512}$/.test(String(t))
  }

  function validId(id) {
    return /^[A-Za-z0-9][A-Za-z0-9._-]{0,32}:[A-Za-z0-9_-]{1,512}$/.test(String(id))
  }

  function validUrl(url) {
    return /^https:\/\/[A-Za-z0-9.-]+(?::\d+)?(?:[/?#][^\s]*)?$/.test(String(url))
  }

  function contentFileUrl(path) {
    var value = String(path || "")
    if (!/^\/[A-Za-z0-9_./-]+$/.test(value) || value.indexOf("/../") >= 0)
      return "about:blank"
    return "file://" + encodeURI(value) + "?preview=" + Date.now()
  }

  function openBrowser(url) {
    if (!validUrl(url)) return false
    // The bar process is not a login shell; bare xdg-open is silent.
    // omarchy-launch-browser runs the default browser via uwsm.
    Quickshell.execDetached(["omarchy-launch-browser", url])
    return true
  }

  readonly property int pageSize: {
    var n = parseInt(setting("max", 25), 10)
    if (!(n > 0)) n = 25
    return Math.max(1, Math.min(50, n))
  }
  readonly property int refreshMs: {
    var n = parseInt(setting("refreshIntervalSec", 60), 10)
    if (!(n > 0)) n = 60
    return Math.max(15, Math.min(3600, n)) * 1000
  }

  function refresh() {
    if (listProc.running || root.markAllBusy) return
    var argv = [root.script, "list", "--limit", String(root.pageSize)]
    if (pageToken !== "" && validToken(pageToken)) argv.push("--page", pageToken)
    listProc.command = argv
    listProc.running = true
  }

  function goNextPage() {
    if (!hasNext || listProc.running || root.markAllBusy) return
    var stack = pageStack.slice()
    stack.push(pageToken)
    pageStack = stack
    pageToken = nextPage
    cursor = -1
    refresh()
  }

  function goPrevPage() {
    if (!hasPrev || listProc.running || root.markAllBusy) return
    var stack = pageStack.slice()
    pageToken = stack.pop()
    pageStack = stack
    cursor = -1
    refresh()
  }

  function firstPage() {
    pageToken = ""
    pageStack = []
    cursor = -1
  }

  function titleText() {
    if (root.unread === 1) return "1 unread"
    return root.unread + " unread"
  }

  function rememberDismissed(id) {
    var next = Object.assign({}, root.dismissedIds)
    next[id] = true
    root.dismissedIds = next
  }

  function dismissLocal(id) {
    rememberDismissed(id)
    var next = []
    for (var i = 0; i < messages.length; i++) {
      if (messages[i].id !== id) next.push(messages[i])
    }
    messages = next
    if (unread > 0) unread -= 1
    if (cursor > messages.length - 1) cursor = messages.length - 1
  }

  function openableInboxUrls() {
    var urls = []
    var seen = {}
    var list = root.inboxes || []
    if (list.length === 0 && validUrl(root.searchUrl))
      list = [{ unread: root.unread, searchUrl: root.searchUrl }]
    for (var i = 0; i < list.length; i++) {
      var box = list[i] || {}
      var n = parseInt(box.unread, 10)
      if (!(n > 0)) continue
      var url = box.searchUrl || ""
      if (!validUrl(url) || seen[url]) continue
      seen[url] = true
      urls.push(url)
    }
    return urls
  }

  readonly property bool hasOpenableInbox: openableInboxUrls().length > 0

  function enqueueRead(id) {
    var q = root.readQueue.slice()
    q.push(id)
    root.readQueue = q
    root.pumpRead()
  }

  function pumpRead() {
    if (readProc.running || root.readQueue.length === 0) return
    var q = root.readQueue.slice()
    var id = q.shift()
    root.readQueue = q
    root.pendingId = id
    readProc.command = [root.script, "read", id]
    readProc.running = true
  }

  function openMessageInBrowser(message) {
    if (root.markAllBusy) return
    if (!message || !validId(message.id)) return
    var url = message.url || ""
    if (url !== "") {
      if (!openBrowser(url)) return
    }
    dismissLocal(message.id)
    enqueueRead(message.id)
    close()
  }

  function previewMessage(message) {
    if (root.markAllBusy || previewProc.running) return
    if (!message || !validId(message.id)) return
    if (message.previewAvailable === false) {
      openMessageInBrowser(message)
      return
    }
    cancelMarkAllConfirm()
    root.detailOpen = true
    root.detailBusy = true
    root.detailMessage = Object.assign({}, message)
    root.detailError = ""
    root.detailContentUrl = "about:blank"
    root.remoteContentAllowed = false
    root.previewRequestedId = message.id
    root.previewRetriesRemaining = 2
    root.startPreviewRequest()
  }

  function startPreviewRequest() {
    if (!root.detailOpen || previewProc.running || !root.detailMessage) return
    if (!validId(root.detailMessage.id)) return
    root.detailBusy = true
    root.detailError = ""
    root.detailContentUrl = "about:blank"
    var argv = [root.script, "preview", root.detailMessage.id]
    if (root.remoteContentAllowed) argv.push("--remote")
    previewProc.command = argv
    previewProc.running = true
  }

  function handlePreviewFailure(message) {
    if (!root.detailOpen) return
    root.detailContentUrl = "about:blank"
    if (root.previewRetriesRemaining > 0) {
      root.previewRetriesRemaining -= 1
      root.detailBusy = true
      root.detailError = ""
      previewRetryTimer.restart()
      return
    }
    root.detailBusy = false
    root.detailError = message || "could not load message"
  }

  function retryDetail() {
    if (!root.detailOpen || previewProc.running || !root.detailMessage) return
    previewRetryTimer.stop()
    root.previewRetriesRemaining = 2
    root.startPreviewRequest()
  }

  function closeDetail() {
    root.detailOpen = false
    root.detailBusy = false
    root.detailMessage = null
    root.detailError = ""
    root.detailContentUrl = "about:blank"
    root.previewRequestedId = ""
    root.remoteContentAllowed = false
    root.previewRetriesRemaining = 0
    previewRetryTimer.stop()
  }

  function applyPreviewPayload(text) {
    if (!root.detailOpen) return
    try {
      var data = JSON.parse(text)
      if (data.ok !== true) {
        root.handlePreviewFailure(data.error || "could not load message")
        return
      }
      if (data.id !== root.previewRequestedId) return
      root.detailBusy = false
      root.detailMessage = Object.assign({}, root.detailMessage || {}, data)
      root.detailContentUrl = root.contentFileUrl(data.contentPath)
    } catch (e) {
      root.handlePreviewFailure("unexpected output from you-got-mail")
    }
  }

  function markDetailRead() {
    if (!root.detailMessage || !validId(root.detailMessage.id)) return
    var id = root.detailMessage.id
    dismissLocal(id)
    enqueueRead(id)
    closeDetail()
  }

  function toggleRemoteContent() {
    if (previewProc.running || !root.detailMessage) return
    previewRetryTimer.stop()
    root.remoteContentAllowed = !root.remoteContentAllowed
    root.previewRetriesRemaining = 2
    root.startPreviewRequest()
  }

  function markCursorRead() {
    if (root.markAllBusy) return
    if (cursor < 0 || cursor >= messages.length) return
    var message = messages[cursor]
    if (!message || !validId(message.id)) return
    cancelMarkAllConfirm()
    dismissLocal(message.id)
    enqueueRead(message.id)
  }

  function openSearch() {
    var urls = openableInboxUrls()
    if (urls.length === 0) return
    for (var i = 0; i < urls.length; i++)
      openBrowser(urls[i])
    close()
  }

  function cancelMarkAllConfirm() {
    markAllArmed = false
    if (markAllArmTimer.running) markAllArmTimer.stop()
  }

  function requestMarkAll() {
    if (!root.hasUnread || !root.reachable || root.markAllBusy) return
    if (!root.markAllArmed) {
      root.markAllArmed = true
      markAllArmTimer.restart()
      return
    }
    root.cancelMarkAllConfirm()
    root.markAllBusy = true
    readAllProc.command = [root.script, "read-all"]
    readAllProc.running = true
  }

  function applyReadAllPayload(text) {
    root.markAllBusy = false
    root.cancelMarkAllConfirm()
    root.dismissedIds = ({})
    try {
      var data = JSON.parse(text)
      var marked = parseInt(data.marked, 10)
      if (!(marked > 0)) marked = 0
      if (data.ok === true) {
        root.actionWarning = data.warning || ""
        firstPage()
        refresh()
        return
      }
      root.actionWarning = data.error || "could not mark all as read"
      if (marked > 0) {
        firstPage()
        refresh()
      }
    } catch (e) {
      root.actionWarning = "unexpected output from you-got-mail"
    }
  }

  function moveCursor(delta) {
    if (messages.length === 0) return
    var next = cursor + delta
    if (next < 0) next = 0
    if (next > messages.length - 1) next = messages.length - 1
    cursor = next
    list.positionViewAtIndex(next, ListView.Contain)
  }

  function activateCursor() {
    if (cursor < 0 || cursor >= messages.length) return
    previewMessage(messages[cursor])
  }

  function ageLabel(ts) {
    if (!ts || ts <= 0) return ""
    var seconds = Math.max(0, root.now - ts)
    if (seconds < 60) return "now"
    if (seconds < 3600) return Math.floor(seconds / 60) + "m"
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h"
    if (seconds < 604800) return Math.floor(seconds / 86400) + "d"
    if (seconds < 2592000) return Math.floor(seconds / 604800) + "w"
    return Qt.formatDate(new Date(ts * 1000), "d MMM")
  }

  function oneLine(value) {
    return String(value || "").replace(/\s+/g, " ").trim()
  }

  function applyPayload(text) {
    try {
      var data = JSON.parse(text)
      reachable = data.ok === true
      errorText = data.error || ""
      warningText = reachable ? (data.warning || "") : ""
      // Keep actionWarning across this refresh: a write can fail while list still works.
      if (!reachable) return
      var incoming = data.messages || []
      var kept = []
      var dropped = 0
      for (var i = 0; i < incoming.length; i++) {
        var row = incoming[i]
        if (row && root.dismissedIds[row.id]) dropped += 1
        else kept.push(row)
      }
      messages = kept
      unread = Math.max(0, (data.unread || 0) - dropped)
      email = data.email || ""
      searchUrl = data.searchUrl || ""
      inboxes = data.inboxes || []
      accountCount = data.accountCount || 0
      nextPage = validToken(data.nextPage) ? data.nextPage : ""
      if (cursor > messages.length - 1) cursor = messages.length - 1
    } catch (e) {
      reachable = false
      errorText = "unexpected output from you-got-mail"
    }
  }

  onOpenedChanged: {
    if (opened) {
      now = Date.now() / 1000
      refresh()
    } else {
      cursor = -1
      closeDetail()
      firstPage()
      cancelMarkAllConfirm()
      actionWarning = ""
      dismissedIds = ({})
    }
  }

  Component.onCompleted: now = Date.now() / 1000

  Process {
    id: listProc
    stdout: StdioCollector {
      onStreamFinished: root.applyPayload(text)
    }
  }

  IpcHandler {
    target: root.ipcTarget

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { root.refresh(); return "ok" }
    function previewFirst(): string {
      root.open()
      if (root.messages.length === 0) {
        root.refresh()
        return "no unread message loaded"
      }
      root.previewMessage(root.messages[0])
      return "ok"
    }
  }

  Process {
    id: readProc
    onExited: function(exitCode) {
      root.pendingId = ""
      if (root.readQueue.length > 0) {
        root.pumpRead()
        return
      }
      root.refresh()
    }
  }

  Process {
    id: previewProc
    stdout: StdioCollector {
      onStreamFinished: root.applyPreviewPayload(text)
    }
  }

  Timer {
    id: previewRetryTimer
    interval: 500
    repeat: false
    onTriggered: root.startPreviewRequest()
  }

  Process {
    id: readAllProc
    stdout: StdioCollector {
      onStreamFinished: root.applyReadAllPayload(text)
    }
  }

  Timer {
    interval: root.refreshMs
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: {
      root.now = Date.now() / 1000
      root.refresh()
    }
  }

  Timer {
    id: markAllArmTimer
    interval: 4000
    repeat: false
    onTriggered: root.markAllArmed = false
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    opacity: root.reachable ? 1 : 0.5
    slotSize: root.barSlot
    opticalSize: root.barContentWidth
    tooltipText: !root.reachable
      ? (root.errorText !== "" ? root.errorText : "Mail unreachable")
      : (root.hasUnread ? (root.unread === 1 ? "1 unread" : root.unread + " unread") : "No unread mail")

    iconComponent: Component {
      Item {
        Row {
          anchors.centerIn: parent
          spacing: Style.space(5)

          MailSlotIcon {
            anchors.verticalCenter: parent.verticalCenter
            iconSize: Style.bar.iconCanvas
            color: button.foreground
            flagColor: button.foreground
            hasMail: root.hasUnread && root.reachable
          }

          Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.reachable && root.badgeCount > 0
            height: Style.space(12)
            width: root.badgeWidth
            radius: height / 2
            color: Qt.rgba(button.foreground.r, button.foreground.g,
                           button.foreground.b, 0.14)

            Text {
              anchors.centerIn: parent
              text: root.badgeCount
              textFormat: Text.PlainText
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              renderType: Text.NativeRendering
              color: button.foreground
            }
          }
        }
      }
    }

    onPressed: function(b) {
      if (b === Qt.RightButton) {
        root.openSearch()
      } else if (b === Qt.MiddleButton) {
        root.refresh()
      } else {
        root.toggle()
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(root.detailOpen ? Style.space(720) : Style.space(400))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    Behavior on contentWidth {
      NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
    }

    Behavior on contentHeight {
      NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
    }

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: {
        if (root.detailOpen) {
          root.closeDetail()
          return
        }
        if (root.markAllArmed) {
          root.cancelMarkAllConfirm()
          return
        }
        root.close()
      }
      onMoveRequested: function(dx, dy) {
        if (!root.detailOpen && dy !== 0) root.moveCursor(dy)
      }
      onActivateRequested: if (!root.detailOpen) root.activateCursor()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (root.detailOpen) {
          if (t === "a")
            root.markDetailRead()
          else if (t === "o" && root.detailMessage)
            root.openMessageInBrowser(root.detailMessage)
          else if (t === "b")
            root.closeDetail()
          else if (t === "r" && root.detailMessage && root.detailMessage.hasRemoteContent)
            root.toggleRemoteContent()
          return
        }
        var onCursor = root.cursor >= 0 && root.cursor < root.messages.length
        if (t === "o" && onCursor)
          root.openMessageInBrowser(root.messages[root.cursor])
        else if (t === "i" && root.hasOpenableInbox)
          root.openSearch()
        else if (t === "a")
          root.markCursorRead()
        else if (t === "A")
          root.requestMarkAll()
        else if (t === "n")
          root.goNextPage()
        else if (t === "p")
          root.goPrevPage()
      }

      Item {
        id: content
        anchors.fill: parent
        implicitHeight: root.detailOpen ? detailPane.implicitHeight : inboxPane.implicitHeight

        Column {
          id: inboxPane
          width: parent.width
          visible: !root.detailOpen
          spacing: Style.space(6)

        Item {
          width: parent.width
          height: Math.max(heading.implicitHeight, openMailButton.height)

          Column {
            id: heading
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: headerActions.left
            anchors.rightMargin: Style.space(8)
            spacing: Style.space(1)

            PanelSectionHeader {
              width: parent.width
              text: root.titleText()
              textFormat: Text.PlainText
              elide: Text.ElideRight
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              width: parent.width
              visible: root.email !== ""
              text: root.email
              textFormat: Text.PlainText
              elide: Text.ElideRight
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: Qt.darker(root.foreground, 1.6)
            }
          }

          Row {
            id: headerActions
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            PanelActionButton {
              id: markAllButton
              visible: root.hasUnread && root.reachable
              enabled: root.hasUnread && root.reachable && !root.markAllBusy
              iconText: root.markAllArmed || root.markAllBusy
                ? root.iconConfirm : root.iconMarkAll
              tooltipText: root.markAllBusy
                ? "Marking unread mail as read…"
                : (root.markAllArmed
                  ? "Click again to confirm"
                  : "Mark all unread as read (A)")
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.requestMarkAll()
            }

            PanelActionButton {
              id: openMailButton
              visible: root.hasOpenableInbox
              enabled: root.hasOpenableInbox && !root.markAllBusy
              iconText: root.iconExternal
              tooltipText: root.accountCount > 1
                ? "Open each unread inbox in the browser (i)"
                : "Open unread in browser (i)"
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.openSearch()
            }
          }
        }

        PanelSeparator { width: parent.width }

        Item {
          width: parent.width
          height: root.reachable ? 0 : staleWarning.implicitHeight + Style.space(6)
          visible: !root.reachable

          Text {
            id: staleWarning
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            text: root.errorText !== ""
              ? root.errorText
              : "Could not reach mail. Showing the last list."
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: bar ? bar.urgent : Color.urgent
          }
        }

        Item {
          width: parent.width
          height: (root.reachable && root.warningText !== "")
            ? partialWarning.implicitHeight + Style.space(6) : 0
          visible: root.reachable && root.warningText !== ""

          Text {
            id: partialWarning
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            text: root.warningText
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: bar ? bar.urgent : Color.urgent
          }
        }

        Item {
          width: parent.width
          height: (root.actionWarning !== "" && !root.markAllBusy)
            ? actionWarningLabel.implicitHeight + Style.space(6) : 0
          visible: root.actionWarning !== "" && !root.markAllBusy

          Text {
            id: actionWarningLabel
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            text: root.actionWarning
            textFormat: Text.PlainText
            elide: Text.ElideRight
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: bar ? bar.urgent : Color.urgent
          }
        }

        Item {
          width: parent.width
          height: root.markAllBusy ? markAllBusyLabel.implicitHeight + Style.space(6) : 0
          visible: root.markAllBusy

          Text {
            id: markAllBusyLabel
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            text: "Marking unread mail as read…"
            textFormat: Text.PlainText
            elide: Text.ElideRight
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: Qt.darker(root.foreground, 1.6)
          }
        }

        ListView {
          id: list
          width: parent.width
          visible: root.messages.length > 0
          clip: true
          opacity: root.markAllBusy ? 0.4 : 1
          enabled: !root.markAllBusy
          model: root.messages
          spacing: Style.space(1)
          boundsBehavior: Flickable.StopAtBounds
          flickableDirection: Flickable.VerticalFlick
          interactive: contentHeight > height && !root.markAllBusy
          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          readonly property int cap: {
            var chrome = Style.space(70)
            if (root.hasPrev || root.hasNext) chrome += Style.space(38)
            if (!root.reachable) chrome += staleWarning.implicitHeight + Style.space(6)
            if (root.reachable && root.warningText !== "")
              chrome += partialWarning.implicitHeight + Style.space(6)
            if (root.actionWarning !== "" && !root.markAllBusy) chrome += Style.space(24)
            if (root.markAllBusy) chrome += Style.space(24)
            return Math.max(Style.space(200),
                            panel.availableCardHeight - panel.verticalContentInset - chrome)
          }
          height: Math.min(contentHeight, cap)

          delegate: Rectangle {
            id: row
            required property var modelData
            required property int index

            readonly property bool active: root.cursor === row.index || rowMouse.containsMouse

            width: list.width - (list.interactive ? Style.space(10) : 0)
            height: rowContent.implicitHeight + Style.space(10)
            radius: Style.cornerRadius
            opacity: root.pendingId === modelData.id ? 0.4 : 1
            color: active
              ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08)
              : "transparent"

            Behavior on color { ColorAnimation { duration: 80 } }

            MouseArea {
              id: rowMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onContainsMouseChanged: if (containsMouse) root.cursor = row.index
              onClicked: if (!root.markAllBusy) root.previewMessage(row.modelData)
            }

            Column {
              id: rowContent
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.leftMargin: Style.space(6)
              anchors.rightMargin: Style.space(6)
              spacing: Style.space(2)

              Item {
                width: parent.width
                height: subject.implicitHeight

                Row {
                  id: line
                  anchors.left: parent.left
                  anchors.right: age.left
                  anchors.rightMargin: Style.space(6)
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(5)

                  Row {
                    id: chips
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(3)
                    visible: {
                      var labs = row.modelData.labels || []
                      var acc = row.modelData.account || ""
                      return labs.length > 0 || (root.accountCount > 1 && acc !== "")
                    }

                    Repeater {
                      model: {
                        var labs = (row.modelData.labels || []).slice()
                        var acc = row.modelData.account || ""
                        if (acc && root.accountCount > 1) labs.unshift(acc)
                        return labs.slice(0, 2)
                      }

                      Rectangle {
                        required property string modelData
                        anchors.verticalCenter: parent.verticalCenter
                        height: chipText.implicitHeight + Style.space(3)
                        width: chipText.width + Style.space(8)
                        radius: Style.space(3)
                        color: Qt.rgba(root.foreground.r, root.foreground.g,
                                       root.foreground.b, 0.14)

                        Text {
                          id: chipText
                          anchors.centerIn: parent
                          text: parent.modelData
                          textFormat: Text.PlainText
                          elide: Text.ElideRight
                          wrapMode: Text.NoWrap
                          maximumLineCount: 1
                          width: Math.min(implicitWidth, Style.space(64))
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                          color: Qt.darker(root.foreground, 1.35)
                        }
                      }
                    }
                  }

                  Text {
                    id: subject
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(Style.space(40),
                                    line.width - (chips.visible ? chips.width + line.spacing : 0))
                    text: root.oneLine(row.modelData.subject)
                    textFormat: Text.PlainText
                    wrapMode: Text.NoWrap
                    maximumLineCount: 1
                    elide: Text.ElideRight
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    color: root.foreground
                  }
                }

                Text {
                  id: age
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  text: root.ageLabel(row.modelData.ts)
                  textFormat: Text.PlainText
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  color: Qt.darker(root.foreground, 1.7)
                }
              }

              Row {
                width: parent.width
                spacing: 0

                Text {
                  id: fromLabel
                  text: row.modelData.from || ""
                  textFormat: Text.PlainText
                  elide: Text.ElideRight
                  width: Math.min(implicitWidth, parent.width * 0.5)
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  color: Qt.darker(root.foreground, 1.15)
                }

                Text {
                  text: {
                    var body = root.oneLine(row.modelData.snippet)
                    if (body === "") return ""
                    return (fromLabel.text !== "" ? "  -  " : "") + body
                  }
                  textFormat: Text.PlainText
                  wrapMode: Text.NoWrap
                  maximumLineCount: 1
                  elide: Text.ElideRight
                  width: parent.width - fromLabel.width
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  color: Qt.darker(root.foreground, 1.7)
                }
              }
            }
          }
        }

        Item {
          width: parent.width
          height: (root.hasPrev || root.hasNext) ? pagerRow.implicitHeight + Style.space(8) : 0
          visible: root.hasPrev || root.hasNext

          Row {
            id: pagerRow
            anchors.centerIn: parent
            spacing: Style.space(10)

            PanelActionButton {
              iconText: root.iconPrev
              tooltipText: "Previous page"
              enabled: root.hasPrev && !root.markAllBusy
              opacity: enabled ? 1 : 0.3
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.goPrevPage()
            }

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: "page " + (root.pageStack.length + 1)
              textFormat: Text.PlainText
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              color: Qt.darker(root.foreground, 1.7)
            }

            PanelActionButton {
              iconText: root.iconNext
              tooltipText: "Next page"
              enabled: root.hasNext && !root.markAllBusy
              opacity: enabled ? 1 : 0.3
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.goNextPage()
            }
          }
        }

        Item {
          width: parent.width
          height: root.messages.length === 0 ? Style.space(60) : 0
          visible: root.messages.length === 0

          Text {
            anchors.centerIn: parent
            width: parent.width - Style.space(20)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.reachable
              ? "You're all caught up."
              : "Fix sign-in from a terminal, then middle-click the icon."
            textFormat: Text.PlainText
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            color: root.foreground
            opacity: 0.6
          }
        }
        }

        Column {
          id: detailPane
          width: parent.width
          visible: root.detailOpen
          spacing: Style.space(6)

          Item {
            width: parent.width
            height: Math.max(detailHeading.implicitHeight, detailActions.height)

            PanelActionButton {
              id: backButton
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              iconText: root.iconBack
              tooltipText: "Back to unread mail (b or Esc)"
              foreground: root.foreground
              hoverColor: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.iconSmall
              onClicked: root.closeDetail()
            }

            Column {
              id: detailHeading
              anchors.left: backButton.right
              anchors.leftMargin: Style.space(8)
              anchors.right: detailActions.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              PanelSectionHeader {
                width: parent.width
                text: root.detailMessage ? root.detailMessage.subject || "(no subject)" : "Loading message…"
                textFormat: Text.PlainText
                elide: Text.ElideRight
                foreground: root.foreground
                fontFamily: root.fontFamily
              }

              Text {
                width: parent.width
                text: root.detailMessage ? root.detailMessage.from || "" : ""
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                color: Qt.darker(root.foreground, 1.2)
              }

              Text {
                width: parent.width
                text: {
                  if (!root.detailMessage) return ""
                  var pieces = []
                  if (root.detailMessage.to) pieces.push("to " + root.detailMessage.to)
                  if (root.detailMessage.date) pieces.push(root.detailMessage.date)
                  var files = root.detailMessage.attachments || []
                  if (files.length > 0)
                    pieces.push(files.length === 1 ? "1 attachment" : files.length + " attachments")
                  return pieces.join("  ·  ")
                }
                textFormat: Text.PlainText
                elide: Text.ElideRight
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                color: Qt.darker(root.foreground, 1.7)
              }
            }

            Row {
              id: detailActions
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              PanelActionButton {
                visible: root.detailMessage && root.detailMessage.hasRemoteContent === true
                iconText: root.iconImages
                tooltipText: root.remoteContentAllowed
                  ? "Block remote images (r)"
                  : "Load remote images (r)"
                foreground: root.remoteContentAllowed ? root.accent : root.foreground
                hoverColor: root.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.iconSmall
                onClicked: root.toggleRemoteContent()
              }

              PanelActionButton {
                visible: root.detailMessage !== null
                enabled: !root.detailBusy
                iconText: root.iconMarkAll
                tooltipText: "Mark this message as read (a)"
                foreground: root.foreground
                hoverColor: root.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.iconSmall
                onClicked: root.markDetailRead()
              }

              PanelActionButton {
                visible: root.detailMessage && root.detailMessage.url
                enabled: !root.detailBusy
                iconText: root.iconExternal
                tooltipText: "Open in Gmail (o)"
                foreground: root.foreground
                hoverColor: root.accent
                fontFamily: root.fontFamily
                fontSize: Style.font.iconSmall
                onClicked: root.openMessageInBrowser(root.detailMessage)
              }
            }
          }

          PanelSeparator { width: parent.width }

          Rectangle {
            id: previewFrame
            width: parent.width
            readonly property int heightCap: Math.max(
              Style.space(180),
              panel.availableCardHeight - panel.verticalContentInset
                - detailHeading.implicitHeight - Style.space(62))
            readonly property real previewScale: width / 720
            readonly property real renderedImageWidth: {
              var imageWidth = root.detailMessage ? Number(root.detailMessage.previewWidth) : 0
              if (!(imageWidth > 0)) imageWidth = 720
              return imageWidth * previewScale
            }
            readonly property real fittedImageHeight: {
              var imageHeight = root.detailMessage ? Number(root.detailMessage.previewHeight) : 0
              if (!(imageHeight > 0)) return Style.space(180)
              return imageHeight * previewScale
            }
            height: Math.min(heightCap, Math.max(Style.space(80), fittedImageHeight))
            radius: Style.cornerRadius
            color: "#ffffff"
            clip: true

            Loader {
              id: previewLoader
              anchors.fill: parent
              active: root.detailOpen && !root.detailBusy
                      && root.detailError === ""
                      && root.detailContentUrl !== "about:blank"

              sourceComponent: Component {
                Flickable {
                  id: previewFlickable
                  anchors.fill: parent
                  clip: true
                  boundsBehavior: Flickable.StopAtBounds
                  flickableDirection: Flickable.AutoFlickDirection
                  contentWidth: previewImage.width
                  contentHeight: previewImage.height
                  interactive: contentWidth > width || contentHeight > height
                  ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                  ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                  Image {
                    id: previewImage
                    property int loadRetries: 0
                    property string requestedSource: root.detailContentUrl

                    width: previewFrame.renderedImageWidth
                    height: previewFrame.fittedImageHeight
                    source: requestedSource
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    cache: false
                    smooth: true
                    onStatusChanged: {
                      if (status !== Image.Error) return
                      if (loadRetries < 2) {
                        loadRetries += 1
                        imageRetryTimer.restart()
                      } else {
                        root.handlePreviewFailure("could not display message")
                      }
                    }

                    Timer {
                      id: imageRetryTimer
                      interval: 200
                      repeat: false
                      onTriggered: previewImage.requestedSource = root.detailContentUrl
                        + "&imageRetry=" + previewImage.loadRetries
                    }
                  }
                }
              }
            }

            Text {
              anchors.centerIn: parent
              width: parent.width - Style.space(40)
              visible: root.detailBusy || root.detailError !== ""
              text: root.detailBusy
                ? (root.previewRetriesRemaining < 2 ? "Retrying the full message…" : "Loading the full message…")
                : root.detailError + "\nClick to retry."
              textFormat: Text.PlainText
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              color: root.detailError !== "" ? "#a51d2d" : "#444444"

              MouseArea {
                anchors.fill: parent
                enabled: root.detailError !== "" && !root.detailBusy
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.retryDetail()
              }
            }
          }
        }
      }
    }
  }
}
