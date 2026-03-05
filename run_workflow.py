import asyncio
from phalanx_core.yaml.parser import parse_workflow_yaml
from phalanx_core.state import WorkflowState
from phalanx_core.primitives import Task


async def main():
    # Load the workflow
    with open("custom/workflows/landing_page.yaml", "r") as f:
        yaml_content = f.read()

    workflow = parse_workflow_yaml(yaml_content)
    print(f"Loaded workflow: {workflow.name}")

    # Run the workflow
    initial_prompt = "A SaaS platform that uses AI to automatically generate personalized cold emails for B2B sales teams based on a prospect's LinkedIn profile."
    print(f"Starting workflow with prompt: {initial_prompt}\n")

    initial_task = Task(id="task_1", instruction=initial_prompt)
    initial_state = WorkflowState(current_task=initial_task)

    final_state = await workflow.run(initial_state=initial_state)

    print("\n" + "=" * 50)
    print("WORKFLOW COMPLETED")
    print("=" * 50)
    print(f"Total Cost: ${final_state.total_cost_usd:.4f}")
    print(f"Total Tokens: {final_state.total_tokens:,}")

    # Save the output
    html_output = final_state.results.get("code_block", "")

    # Clean up markdown if present
    if html_output.startswith("```html"):
        html_output = html_output[7:]
    if html_output.endswith("```"):
        html_output = html_output[:-3]

    with open("landing_page.html", "w") as f:
        f.write(html_output.strip())

    print("\nSaved output to landing_page.html!")


if __name__ == "__main__":
    asyncio.run(main())
