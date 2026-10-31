# What we learned from asking Kolibri to build an email parser

Kolibri wrote useful code, used tools and improved parts of its implementation
after review. None of the reviewed coding attempts delivered the complete email
parser. We found problems in both the implementation and the software controlling
the agent. The evidence does not support one explanation for every failure.

The practical result is that supervised development remains a reasonable use to
explore. Reliable, independent completion of this particular project has not been
demonstrated.

## The job, explained through Alice and Bob

Alice asks Kolibri to build software that understands the structure of an email.
If Bob replies to Alice, the software should distinguish Bob's new words from
quoted history, signatures and mailing-list footers. It should handle several
languages and preserve the original message.

Attachments make this harder. An attached email can contain another conversation,
but its contents must not be mistaken for the current message. The parser should
describe attachments without treating their contents as ordinary body text. It
also needs to handle damaged messages, preserve text positions and save results
without exposing private content or overwriting an existing file.

Alice and Bob are fictional characters used to explain the task. These examples
are illustrative; no private correspondence is reproduced.

This is a software-engineering assignment. The finished parser must work through
deterministic rules, without calling a language model to interpret each message.
Writing a convincing explanation of that design is only the beginning: the
features must actually work together when someone uses the software.

## Useful parts did not add up to a finished product

In the latest completed independent attempt, Kolibri finished after about
28 minutes and 32 seconds. All 21 supplied tests and ten tests it added passed.
It also passed 24 of 27 additional synthetic checks.

That sounds close to success. Inspection of the implementation showed a larger
gap: several components existed but were not connected to the main processing
path. Some required recognition and email-processing behavior therefore could
not be reached through the public interface. Additional checks also found unsafe
output handling and missing warnings for damaged email structures.

Passing 24 checks does not mean that 89 percent of the project was complete.
Those checks sampled particular behaviors; they did not cover every requirement.
The original tests were also too limited to establish completion by themselves.

Kolibri ended that attempt voluntarily. It had not exhausted its context,
request, token or tool budgets. Removing the overall time limit did not make
it finish the missing work. More time is useful only if the agent continues
working toward a reliable definition of completion.

## The repeated-reading problem was real, but was not the whole story

An older attempt spent 22 completed turns repeatedly reading the same three
unchanged files. That consumed 66 tool calls without producing the needed
progress. We have not established why it entered that cycle.

Later attempts did not show that exact cycle, yet still left the project
unfinished. In the guided attempt, the observed pattern was different: Kolibri
rewrote the email-processing code and ran tests, but several corrections left
the same failures unresolved or introduced another failure.

These are different behaviors. Fixing file access or allowing more tool calls
cannot by itself establish that the agent will diagnose a failed test, correct
the right cause and verify the complete product.

## What changed when a reviewer gave feedback

We then tried guided development. Kolibri received one milestone at a time.
A coordinator checked the result and returned concrete findings before the next
milestone could begin. Kolibri still wrote the parser code; the coordinator
did not supply an implementation or an earlier solution.

This produced an observable improvement in integration. The main interface
began calling the recognition rules, language dictionaries and processing
components. Negative tests became more meaningful after the reviewer pointed
out assertions that could pass even when detection was wrong. Basic text
processing was accepted for progression, with a documented limitation: automatic
language selection still defaulted to English.

The email-formatting milestone remained unfinished. Two earlier crashes involving
a damaged multipart message and an unknown character encoding were corrected.
The final source still omitted metadata for an attached email, retained an unsafe
error fallback and lacked later safety and conflict-resolution work.

The guided coding period lasted about 69 minutes, including review waits, and
used 90 model requests and 168 tool calls. The later safety and final-delivery
milestones were not reached. Guidance helped particular parts; it did not produce
an accepted complete parser in this experiment. Tool versions and other trial
conditions also changed, so this was not a controlled measurement of guidance
alone.

## Some of Kolibri's own tests were wrong

The final guided test run discovered 56 tests and reported three failures.
Independent review found that two of those failures came from faulty test
assumptions.

One test marked the entire message as an attachment, then expected the parser to
invent a separate message body inside it. Returning no body was the safe outcome.
Another test omitted a required separator in its synthetic email, so it did not
actually describe the separate body it claimed to test.

The third failure was different: a correctly formed attached email was missing
from attachment metadata. That was a real implementation defect.

The distinction matters. A red test can reveal a bug in the program or a mistake
in the test. A reviewer must check both. Rewriting correct handling to satisfy
an invalid example can make the software less safe. The complete project also
had unresolved requirements beyond these three test results.

## A second problem appeared in the agent's answer budget

The guided attempt eventually stopped because the last response reached its
requested length limit. It was allowed only 1,607 output tokens, although the
configured per-response ceiling was 32,768. Almost all of those 1,607 tokens were
used for reasoning, leaving almost no final output.

The model server reported roughly 164,000 input tokens against an available
context of 262,144. The total request, tool and generated-token budgets were
also not exhausted. The requested answer allowance had progressively shrunk as
the conversation grew. Automatic conversation compaction and pruning were
disabled in this experiment.

This is a concrete orchestration finding: the surrounding agent system limited
the next answer before the server's full context was consumed. We have not
established the exact calculation responsible for that reduction or proved
that enabling one setting would solve it. Context capacity, answer allowance
and total experiment budget are separate limits.

It explains the final truncation, but it does not explain away the earlier
implementation gaps, faulty tests or independent attempts that stopped normally.
A future trial needs verified context management as well as better completion
checks.

## What the earlier evaluations tell us

Separate general evaluations and basic tool tests showed useful capabilities.
The following figures are means from a small, fixed English selection, with
32 distinct examples per task repeated three times:

| Task | Before cache calibration | After cache calibration |
| --- | ---: | ---: |
| Following explicit instructions, IFEval | 91.67% | 88.54% |
| Knowledge and reasoning questions, MMLU-Pro | 45.83% | 50.00% |
| Date understanding, BBH subset | 84.38% | 84.38% |
| Three-object logic, BBH subset | 100.00% | 100.00% |

Calibration adjusted internal cache scales; it did not train the model's weights.
The changes were mixed, with no demonstrated universal improvement or isolated
causal effect. These are subset results, not full-suite benchmark scores.
Repeating the same examples did not create three times as many independent
questions.

The evaluation allowed 4,096 output tokens per response, including reasoning.
Some responses hit that limit and remained counted in the scores: 53 of 384
responses before calibration and 51 of 384 afterwards. We do not know how those
answers would have scored with a different allowance.

The basic tool pilot passed nine calls, but those were only three distinct simple
cases repeated across three seeds. Real browser tool use was also demonstrated.
Neither result establishes reliable handling of a long sequence of coding and
debugging decisions. Serving performance was measured separately on short
requests; it cannot establish complete-project correctness or useful reasoning
through an entire long context.

There is no qualified held-out email accuracy score or completed SWE-bench result
to report. No controlled coding comparison establishes calibration or FP8 as the
cause of the coding failures.

## What we can reasonably conclude

**Kolibri can generate code and use tools.** The attempts contain real code
changes, successful executions and responses to review. Calling the model
entirely nonfunctional would misrepresent those observations.

**Reliable completion was the missing capability in this workflow.** Components,
tests and completion reports did not consistently match the full requirements.
A successful small test suite was an inadequate stopping rule.

**The surrounding software contributed its own failures.** Earlier transport and
session problems were genuine, and the guided attempt exposed a shrinking answer
allowance. Those issues must be measured separately from defects in generated code.

**Supervision helped, without establishing autonomous delivery.** Feedback improved
specific behavior and exposed test mistakes. It also changed the experiment:
guided work cannot be presented as an independent coding success.

**The evidence does not establish a universal verdict about the model.** It shows
that this task was not completed under the tested conditions. It does not prove
that Kolibri can never build a parser, that one configuration change guarantees
success, or that another model would do better under identical conditions.

## A better next experiment

First, test context handling on a harmless long interaction. Check that enough
answer space remains available, that any summary preserves the relevant facts
and that all extra calls count toward the same experiment budget.

Then use small, observable implementation steps. A single well-formed attached
email and a clearly specified expected result are more informative than another
large rewrite. Check the validity of failing examples before changing the parser.
Keep the supplied tests unchanged and use an independent requirements review
before declaring the project finished.

To compare methods, keep the model, tools, sampling, inputs and budgets matched;
record guidance as an experimental difference. Claims about real email quality
need a separate, properly reviewed evaluation with held-out examples.

The current evidence supports continued supervised experiments with verified
increments. A complete, independently accepted email parser remains to be delivered.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
