# cloud-cost-anomaly

Detect unusual cloud spend from billing exports and explain which service, account or tag caused it.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A command-line tool.

**The problem it solves:** Cost spikes are usually found on the invoice, weeks after the change that caused them.

## Who it is for

Platform and FinOps teams who want to catch cost spikes within a day.

## How it will work

1. You point the tool at your cloud billing export.
2. It compares each day's spend per service, account and tag with its normal range.
3. For each anomaly it names the line items responsible and sends an alert.

## Planned features

Unticked items are not built yet.

- [ ] Reads AWS, Google Cloud and Azure billing exports
- [ ] Daily anomaly detection per service, account and tag
- [ ] Explains each anomaly by its largest contributing line items
- [ ] Slack or webhook alerts
- [ ] No write access to cloud accounts required

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
cloud-cost-anomaly scan --export s3://billing/cur/ --days 30
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
