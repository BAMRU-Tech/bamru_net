// What the charts (templates/charts/share_panels.html) need a script for.
// Load it with defer. Without it a chart shows the option it was drawn with,
// its menu stays hidden, and its switches and the pointer work as they do
// with it. Each plot is one stop for the Tab key either way; without the
// script it shows no figures there, though a screen reader still reads them.
(function () {
  // From a plot the arrow keys, Home and End move along its columns, showing
  // each one's figures; Escape goes back to the plot, and Tab moves on.
  document.documentElement.classList.add('chart-scripted');

  document.addEventListener('keydown', function (event) {
    var plot = event.target.closest ? event.target.closest('.chart-plot') : null;
    if (!plot) { return; }
    // With Alt, Ctrl or Cmd an arrow is the browser's (back and forward).
    if (event.altKey || event.ctrlKey || event.metaKey) { return; }
    var bands = Array.prototype.slice.call(plot.querySelectorAll('.chart-band'));
    var at = bands.indexOf(event.target.closest('.chart-band'));
    var to = {ArrowRight: at + 1, ArrowLeft: at < 0 ? bands.length - 1 : at - 1,
              Home: 0, End: bands.length - 1}[event.key];
    if (event.key === 'Escape' && at >= 0) {
      plot.focus();
    } else if (to !== undefined && bands[to]) {
      bands[to].focus();
    } else if (to === undefined) {
      return;
    }
    event.preventDefault();
  });

  // The menu on a chart (charts.with_menu). Every option's title and plots
  // are in the page, in <template> elements; choosing one puts a copy of
  // them inside the elements that show the title and the plots, which stay,
  // so that a screen reader is told of the new title (it is a live region)
  // and the title's place keeps its height.
  // The chart's switches are outside them, so they keep their settings.
  document.addEventListener('change', function (event) {
    var menu = event.target.closest ? event.target.closest('.chart-menu select') : null;
    if (!menu) { return; }
    var chart = menu.closest('.chart');
    var option = chart.querySelector('template[data-chart-option="' + menu.value + '"]');
    if (!option) { return; }
    option.content.querySelectorAll('[data-chart-part]').forEach(function (part) {
      var shown = chart.querySelector('[data-chart-part="' + part.getAttribute('data-chart-part') + '"]');
      if (!shown) { return; }
      // What is marked to be kept stays: the unseen titles that hold the head's height.
      Array.prototype.slice.call(shown.childNodes).forEach(function (child) {
        if (!(child.hasAttribute && child.hasAttribute('data-chart-keep'))) { shown.removeChild(child); }
      });
      shown.prepend.apply(shown, Array.prototype.slice.call(part.cloneNode(true).childNodes));
    });
  });
}());
