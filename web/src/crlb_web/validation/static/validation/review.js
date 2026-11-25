// Highlight a row's source words in the PDF; open the review panel of a row
document.querySelectorAll('tr[data-key]').forEach(row => {
  const boxes = () => document.querySelectorAll('.box.mark.k' + row.dataset.key);
  row.addEventListener('mouseenter', () => boxes().forEach(b => b.classList.add('on')));
  row.addEventListener('mouseleave', () => boxes().forEach(b => b.classList.remove('on')));
  row.addEventListener('click', event => {
    if (event.target.closest('button, form, a')) return;
    const first = boxes()[0];
    if (first) first.scrollIntoView({behavior: 'smooth', block: 'center'});
  });
});
document.querySelectorAll('button.toggle').forEach(button => {
  button.addEventListener('click', () => {
    const panel = document.getElementById(button.dataset.panel);
    panel.hidden = !panel.hidden;
  });
});
// The correction form starts from the current value of the chosen column
document.querySelectorAll('form.correct select[name=column]').forEach(select => {
  select.addEventListener('change', () => {
    select.form.elements.value.value = select.selectedOptions[0].dataset.value;
  });
});
// After a decision, open the panel of the row it was made on
if (location.hash) {
  const panel = document.getElementById('panel-' + decodeURIComponent(location.hash.slice(1)));
  if (panel) panel.hidden = false;
}
