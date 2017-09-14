function generalPdfExportCustomize(doc) {
    if(doc.content) {
        var self = this;
        doc.content.forEach(function(content) {
            if(content.layout) {
                //noinspection JSUndefinedPropertyAssignment
                content.layout = "";
            }
            if (self.exportOptions && self.exportOptions.columnsWidth && content.table) {
                content.table.widths = self.exportOptions.columnsWidth;
            }

        });
    }
}

function tableBulkInit($table, $bulk_action_dropdown) {
    function getSelectionsCount() {
        return $table.find('tr td:first-of-type input[type="checkbox"]:checked').length;
    }
    function getNonSelectionsCount() {
        return $table.find('tr td:first-of-type input[type="checkbox"]:not(:checked)').length;
    }

    //noinspection JSUnusedLocalSymbols
    return $table.tablecheckbox().on('rowselect', function(e, row) {
        var selectionCount = getSelectionsCount(),
            nonSelectionCount = getNonSelectionsCount();
        $bulk_action_dropdown.find('.badge').text(selectionCount);
        $bulk_action_dropdown.attr('disabled', false);
        if(nonSelectionCount == 0) {
            th_cb = $(this).find('th:first-of-type input[type="checkbox"]')[0];
            if (th_cb) {
                th_cb.checked = true;
            }
        }

    }).on('rowdeselect', function(e, row) {
        var th_cb = $(this).find('th:first-of-type input[type="checkbox"]')[0],
            selectionCount = getSelectionsCount();
        if (th_cb) {
            th_cb.checked = false;
        }
        $bulk_action_dropdown.find('.badge').text(selectionCount);
        if (selectionCount == 0) {
            $bulk_action_dropdown.attr('disabled', true);
        }
    });
    
}

function tableBulkGetSelectionsId($table) {
    var ids = [];
    $table.find('tr').each(function (i, tr) {
        if ($(tr).find('td:first-of-type input[type="checkbox"]').is(':checked')) {
            ids.push($(tr).attr('data-id'));
        }
    });
    return ids;
}

String.prototype.format = String.prototype.f = function() {
    var s = this,
        i = arguments.length;

    while (i--) {
        s = s.replace(new RegExp('\\{' + i + '\\}', 'gm'), arguments[i]);
    }
    return s;
};

function bindTableRowModalAction(modalId, actionEl, title, message, action) {
    $(actionEl).click(function(e) {
        e.preventDefault();
        var form = $('#{0} form'.f(modalId)),
            _action = action;

        if ((typeof action) === 'function') {
            var id = $(this).parents('tr').attr('data-id');
            _action = action(id);
        }
        if (_action !== undefined) {
            form[0].action = _action;
        }
        $('#{0} .modal-title'.f(modalId)).text(title);
        $('#{0} .modal-body .confirm-message'.f(modalId)).text(message);
        $('#{0}'.f(modalId)).modal('show');
    });
}

function bindTableRowModalBulkAction(modalId, actionEl, table, title, message, action) {
    $(actionEl).click(function(e) {
        e.preventDefault();
        var selectedIds = tableBulkGetSelectionsId($(table)),
            form = $('#{0} form'.f(modalId)),
            _action = action;

        if ((typeof action) === 'function') {
            _action = action(selectedIds);
        }
        if (_action !== undefined) {
            form[0].action = _action;
        }
        $('#{0} .modal-title'.f(modalId)).text(title);
        $('#{0} .modal-body .confirm-message'.f(modalId)).text(message.f(selectedIds.length));
        $('#{0}'.f(modalId)).modal('show');
    });
}

function patchChosenRequired(selector) {
    $(selector || '.chosen-container').prev('select').each(function () {
        this.setAttribute('style', 'display:visible; position:absolute; clip:rect(0,0,0,0)');
    });
}
