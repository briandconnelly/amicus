# Using Pi with amicus

Pi reaches models from many providers, so it needs a little more setup than Codex or Claude.

## Choosing a model

Pi has no default model in amicus.
Set `AMICUS_PI_MODEL` to an exact `provider/id`, or pass `model` on each call; a call with neither is refused before it spends anything.
`pi --list-models` prints the provider and the model in separate columns, so join them with `/`: `openrouter` and `moonshotai/kimi-k3` become `openrouter/moonshotai/kimi-k3`.
`amicus_models` lists the catalog for the providers Pi has credentials for, with full selectors and prices where the catalog has them; a listed model can still refuse a call, for example for lack of credit.

## Logging in

Pi authenticates in one of two ways.
Credentials saved by Pi's interactive `/login <provider>` need nothing more.
A provider's API-key environment variable (for OpenRouter, `OPENROUTER_API_KEY`) has to reach the amicus server's environment, and the plugin's `.mcp.json` does not forward it, so your host must.

If you set `PI_CODING_AGENT_DIR`, make it an absolute path (or `~/…`).
A relative one is refused before any spend and reported on `amicus_backends`, because Pi would resolve it against a different directory for amicus's free checks than for a paid run.

## Prepaid balances

Pi asks the provider for the model's whole output limit on every call, which `amicus_models` lists as `max_output_tokens`.
A prepaid provider such as OpenRouter refuses the call (HTTP 402) unless your balance covers that limit at the model's output price, however little the call would actually spend.
`amicus_models` lists that price as the row's `pricing.output`, in USD per million tokens; a request whose input, cached tokens included, exceeds a `pricing.tiers` threshold is charged that tier's `output` rate instead.
amicus reports the refusal as not retryable.
Either add credit, or cap the model's output in Pi's `models.json` (in `$PI_CODING_AGENT_DIR` when that is set, otherwise `~/.pi/agent/`), for example:

```json
{"providers":{"openrouter":{"modelOverrides":{"moonshotai/kimi-k3":{"maxTokens":32000}}}}}
```

## Errors that retrying won't fix

A provider's bodiless 404 is reported as not temporary, because retrying the same call unchanged is unlikely to help.
Check that the provider in the model id's prefix serves that model (`amicus_models` lists Pi's), and that no `baseUrl` in Pi's `models.json` points Pi at the wrong endpoint.

A provider client's "Region is missing" is reported as not temporary for the same reason.
For Amazon Bedrock, set `AWS_REGION` in the environment the amicus server starts with and restart the server; for another provider, set the region its configuration asks for, or pass a model from a provider that needs none.

## Containment

A `baseUrl` override in Pi's `models.json` can send your prompts to a different endpoint than the provider the model id names; amicus does not inspect it.
A Pi delegate runs shell commands with no sandbox, and a command it starts (a hung or backgrounded process) can outlive the run, because amicus cannot yet find and stop it (#424).
