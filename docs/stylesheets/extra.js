// Redirect earlier flat documentation URLs after Markdown files moved into
// domain folders. This keeps previously opened browser tabs usable.
var pathRedirects = {
   '/architecture/': '/platform/architecture/',
   // Points straight at the final destination rather than the intermediate
   // '/platform/reports/' hop the 2026-08-13 restructure retired -- this map
   // is a flat lookup, not a chain, so a stale two-hop entry would 404.
   '/reports/': '/reference/reports/',
   '/flexibility_market_operation/': '/flexibility/clearing/',
   '/flexibility_providers/': '/flexibility/providers-and-aggregators/',
   '/network_impact_surrogate/': '/flexibility/network-impact-surrogate/',
   '/building_flexibility_management/': '/flexibility/building-flexibility/',
   '/economic_efficiency_validation/': '/flexibility/economic-validation/',
   '/semantic_graph/': '/reference/semantic-graph/',
   '/falkordb_usecases/': '/reference/falkordb/',
   '/dashboard/': '/platform/dashboard/',
   '/usage/': '/getting-started/quickstart/',
   '/installation/': '/getting-started/installation/',
   '/developer_workflow/': '/development/developer-workflow/',
   '/project_hygiene/': '/development/project-hygiene/',
   '/overview/': '/reference/overview/',
   // 2026-08-13 information-architecture restructure: nav dedupe (RETRO-style
   // finding -- 79 nav entries referenced 75 files) plus directory-to-section
   // alignment. Each entry below is one page whose published URL moved.
   '/sdk/CONTRACT/': '/sdk/clearing-contract/',
   '/platform/building-models/': '/sdk/building-models/',
   '/development/public-api/': '/sdk/public-api/',
   '/platform/release-readiness/': '/development/release-readiness/',
   '/platform/projects-and-workflows/': '/projects/projects-and-workflows/',
   '/semantic-layer/semantic-graph/': '/reference/semantic-graph/',
   '/semantic-layer/falkordb/': '/reference/falkordb/',
   '/platform/reports/': '/reference/reports/',
   // Its one section is now part of reports.md -- see "Application Contract".
   '/applications/reports/': '/reference/reports/'
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
