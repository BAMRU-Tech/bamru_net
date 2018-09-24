// Based on https://gist.github.com/taranjeet/71b7826b60f42e5d239cf3b3abbf292f

/*
function updateElementIndex(el, prefix, ndx) {
    var id_regex = new RegExp('(' + prefix + '-\\d+)');
    var replacement = prefix + '-' + ndx;
    if ($(el).attr("for")) $(el).attr("for", $(el).attr("for").replace(id_regex, replacement));
    if (el.id) el.id = el.id.replace(id_regex, replacement);
    if (el.name) el.name = el.name.replace(id_regex, replacement);
}
*/

function addRecord(formPrefix, $addButton) {
    var $total = $('#id_' + formPrefix + '-TOTAL_FORMS');
    var template = $('#empty-' + formPrefix).html();

    var newFormIndex = Number($total.val());
    var newRecord = template.replace(/__prefix__/g, newFormIndex);

    $addButton.before(newRecord);
    $total.val(newFormIndex + 1);

    /*
    var newElement = $(selector).clone(true);
    var total = $('#id_' + prefix + '-TOTAL_FORMS').val();
    newElement.find(':input').each(function() {
        var name = $(this).attr('name').replace('-' + (total-1) + '-', '-' + total + '-');
        var id = 'id_' + name;
        $(this).attr({'name': name, 'id': id}).val('').removeAttr('checked');
    });
    total++;
    $('#id_' + prefix + '-TOTAL_FORMS').val(total);
    $(selector).after(newElement);
    var conditionRow = $('.form-row:not(:last)');
    conditionRow.find('.btn.add-form-row')
    .removeClass('btn-success').addClass('btn-danger')
    .removeClass('add-form-row').addClass('remove-form-row')
    .html('<span class="glyphicon glyphicon-minus" aria-hidden="true"></span>');
    return false;
    */
}

/*
function deleteForm(prefix, btn) {
    var total = parseInt($('#id_' + prefix + '-TOTAL_FORMS').val());
    if (total > 1){
        btn.closest('.form-row').remove();
        var forms = $('.form-row');
        $('#id_' + prefix + '-TOTAL_FORMS').val(forms.length);
        for (var i=0, formCount=forms.length; i<formCount; i++) {
            $(forms.get(i)).find(':input').each(function() {
                updateElementIndex(this, prefix, i);
            });
        }
    }
    return false;
}
*/

function toggleDelete(prefix, index, $deleteCheckbox) {
    var disable = $deleteCheckbox.prop('checked');
    console.log('toggleDelete', prefix, index, disable);
    $deleteCheckbox.closest('form').find('*').each(function() {
        //console.log($(this), $(this).attr('id'));
        var id = $(this).attr('id');
        if (id && id.startsWith('id_' + prefix + '-' + index + '-')
                && !id.endsWith('-id')
                && !id.endsWith('-DELETE')) {
            console.log('toggling disabled!', $(this));
            $(this).prop('disabled', disable);
        }
    });
}

$(document).on('click', '.add-form-row', function(e){
    e.preventDefault();
    addRecord($(this).data('form-prefix'), $(this));
    return false;
});

$(document).on('click', 'input[type=checkbox]', function(e){
    console.log('checkbox event');
    if (!$(this).attr('id').endsWith('-DELETE')) {
        return true;
    }
    var match = $(this).attr('id').match(/^id_(.*)-(.*)-DELETE$/);
    console.log(match);
    var prefix = match[1];
    var index = match[2];
    toggleDelete(prefix, index, $(this));
    return true;
});

/*
$(document).on('click', '.remove-form-row', function(e){
    e.preventDefault();
    deleteForm('form', $(this));
    return false;
});
*/
