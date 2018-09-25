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

function addRecord(formPrefix) {
    var $total = $('#id_' + formPrefix + '-TOTAL_FORMS');
    var template = $('#empty-' + formPrefix).html();
    var $container = $('#container-' + formPrefix);

    var newFormIndex = Number($total.val());
    var newRecord = template.replace(/__prefix__/g, newFormIndex);

    $container.append(newRecord);
    $total.val(newFormIndex + 1);

    $('#id_' + formPrefix + '-' + newFormIndex + '-position').val(newFormIndex + 1);
}

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

function handleSorted(sortEvent) {
    $(sortEvent.to).children().each(function(i){
        $(this).find('input').each(function(){
            if ($(this).attr('id').endsWith('-position')) {
                $(this).val(i);
            }
        });
    });
}

$(document).on('click', '.add-form-row', function(e){
    e.preventDefault();
    addRecord($(this).data('form-prefix'));
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

$(function(){
    $('.sortable').each(function(){
        Sortable.create(this, {
            'animate': 150,
            'handle': '.sort-handle',
            'onEnd': handleSorted,
        });
    });
});
