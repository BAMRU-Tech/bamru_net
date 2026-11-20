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
    kept = null;                // a key ends what a tap kept (below)
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

  // A tap shows a column's figures by focusing it (tabindex="-1"), but a touch
  // screen gives the focus back on no tap elsewhere, and leaves a tapped
  // column under the pointer (charts.css shows figures there by focus alone).
  // So a tap, not a drag that scrolls, is handled here, decided once from what
  // showed as it came down: on another column it shows that one's, on the
  // column showing them or anywhere else but the box it puts them away. What
  // it leaves is kept for the rest of the tap, as the mouse events and the
  // click that may follow it (iOS sends them, whatever pointerdown says) would
  // focus the column again: a mousedown on a column is stopped, a column they
  // focus is let go, and a click puts the tap's choice back, for a second or
  // until the next pointer comes down or a key is pressed.
  var down = null, kept = null;
  function band(event) {
    return event.target.closest ? event.target.closest('.chart-plot .chart-band') : null;
  }
  function settle() {
    var shown = document.activeElement;
    if (kept.shows) { kept.shows.focus({preventScroll: true}); }
    else if (shown && shown.matches && shown.matches('.chart-plot .chart-band')) { shown.blur(); }
  }
  function keeping() {
    if (kept && Date.now() > kept.until) { kept = null; }
    return kept;
  }
  document.addEventListener('pointerdown', function (event) {
    down = kept = null;
    if (!event.isPrimary || event.button !== 0) { return; }
    var shown = document.activeElement;
    down = {x: event.clientX, y: event.clientY,
            shown: shown && shown.matches && shown.matches('.chart-plot .chart-band') ? shown : null};
    if (band(event)) { event.preventDefault(); }
  }, true);
  document.addEventListener('pointerup', function (event) {
    var at = down, on = band(event);
    down = null;
    if (!at || Math.abs(event.clientX - at.x) > 10 || Math.abs(event.clientY - at.y) > 10) { return; }
    var box = on && event.target.closest('.chart-tip');
    kept = {shows: box ? at.shown : on && on !== at.shown ? on : null, until: Date.now() + 1000};
    settle();
  }, true);
  document.addEventListener('mousedown', function (event) {
    if (keeping() && band(event)) { event.preventDefault(); }
  }, true);
  document.addEventListener('focusin', function (event) {
    var on = band(event);
    if (keeping() && on && on !== kept.shows) { on.blur(); }
  }, true);
  document.addEventListener('click', function () {
    if (keeping()) { settle(); }
  }, true);

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
