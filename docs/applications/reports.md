# Reports Application Surface

Reports are both human review artifacts and machine-readable contracts. The
dashboard, regression checks, publication workflows, and future services should
all be able to discover results through reports and manifests.

## Application Contract

Applications should read:

- report manifests;
- scenario summaries;
- operation scorecards;
- validation reports;
- figure inventories;
- semantic graph manifests;
- dashboard catalogs.

They should avoid reading intermediate files unless the file is documented as
part of the application contract.

See [Reports And Manifests](../platform/reports.md) and
[Dashboard](../platform/dashboard.md).
