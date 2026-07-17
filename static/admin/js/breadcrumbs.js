(function () {
  function isSeparatorNode(node) {
    return node && node.nodeType === Node.TEXT_NODE && /›|»|&rsaquo;|\u203a/i.test(node.textContent);
  }

  function removeCoreBreadcrumbLink(link) {
    var prev = link.previousSibling;
    var next = link.nextSibling;
    if (isSeparatorNode(prev)) prev.remove();
    else if (isSeparatorNode(next)) next.remove();
    link.remove();
  }

  function hideCoreBreadcrumbs() {
    document.querySelectorAll('a[href$="/admin/core/"]').forEach(removeCoreBreadcrumbLink);
  }

  document.addEventListener('DOMContentLoaded', hideCoreBreadcrumbs);
})();
