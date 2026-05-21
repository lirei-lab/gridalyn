// Redirect earlier flat documentation URLs after Markdown files moved into
// domain folders. This keeps previously opened browser tabs usable.
var pathRedirects = {
   '/architecture/': '/platform/architecture/',
   '/reports/': '/platform/reports/',
   '/flexibility_market_operation/': '/flexibility/clearing/',
   '/flexibility_providers/': '/flexibility/providers-and-aggregators/',
   '/network_impact_surrogate/': '/flexibility/network-impact-surrogate/',
   '/building_flexibility_management/': '/flexibility/building-flexibility/',
   '/economic_efficiency_validation/': '/flexibility/economic-validation/',
   '/semantic_graph/': '/semantic-layer/semantic-graph/',
   '/falkordb_usecases/': '/semantic-layer/falkordb/',
   '/dashboard/': '/platform/dashboard/',
   '/usage/': '/getting-started/quickstart/',
   '/installation/': '/getting-started/installation/',
   '/developer_workflow/': '/development/developer-workflow/',
   '/project_hygiene/': '/development/project-hygiene/',
   '/overview/': '/reference/overview/'
};

var currentPath = window.location.pathname;
if (pathRedirects[currentPath]) {
   window.location.replace(pathRedirects[currentPath] + window.location.search + window.location.hash);
}

// Open links externally.
var links = document.links;

for (var i = 0, linksLength = links.length; i < linksLength; i++) {
   if (links[i].hostname != window.location.hostname) {
       links[i].target = '_blank';
   }
}
