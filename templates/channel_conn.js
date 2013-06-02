var ChannelConn = {
    connected: false,
    engaged: false,
    initialize: function() {
        this.presentation_key = 'o_key';
        this.channel = new goog.appengine.Channel('token');
        var socket = this.channel.open();
        socket.onopen = this.onOpened;
        socket.onmessage = this.onMessage;
        socket.onerror = this.onError;
        socket.onclose = this.onClose;
        this.socket = socket;
        this.connected = true;
        this.engaged = true;
        // TODO Engage!

    },

    onOpened: function() {
        window.alert('You are now connected')
    },

    onMessage: function(msg) {
        var page = msg.pageNum;
        this.channel_page = page;
        if (this.engaged === true && page !== PDFView.page)
            PDFView.page = page;
    },

    onError: function(msg) {
        console.log(msg);
    },

    onClose: function() {
        window.alert('You have been disconnected')
        this.connected = false;
    },
    emit_page_change: function(page) {
        if (this.engaged === true) {
            var path = '/channel/?p_key=' + this.presentation_key;
            path += '&p=' + page;
            var xhr = new XMLHttpRequest();
            xhr.open('POST', path, true);
            xhr.send();
        }
    }
};

window.addEventListener('pagechange', function pagechange(evt) {
    var page = evt.pageNumber;
    if (PDFView.previousPageNumber !== page) {
        ChannelConn.emit_page_change(page);
    }
}, true);

document.addEventListener('DOMContentLoaded', function webViewerLoad(evt) {
    ChannelConn.initialize();
//    $('#channelEngage').click(function(evt) {
//
//    });
});