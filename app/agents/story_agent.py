# story_agent.py
# Google ADK LlmAgent wrapping Gemini 2.0 Flash for children's story generation.
# Receives a ScenePayload and returns a StoryBeat-compatible JSON object.

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
import json
import logging

logger = logging.getLogger(__name__)

STORY_SYSTEM_PROMPT = """
You are SeeSaw, a gentle and imaginative storytelling companion for children aged 3-8.

You receive a scene (detected objects + optional child speech) and story history.
Generate the next story beat.

RULES (non-negotiable):
- Story text: 2-3 sentences, 40-80 words, simple vocabulary, second-person present tense
- Question: one open-ended question (max 15 words) inviting the child to respond
- Always address the child by their first name
- Never include violence, fear, darkness, monsters (unless friendly), or adult themes
- Never mention technology, AI, cameras, or devices
- is_ending: true ONLY if this is a natural and warm story conclusion

Respond with a JSON object ONLY — no markdown, no explanation:
{"story_text": "...", "question": "...", "is_ending": false}
"""

story_agent = LlmAgent(
    name="seesaw_story_agent",
    model=LiteLlm(model="gemini/gemini-2.0-flash"),
    instruction=STORY_SYSTEM_PROMPT,
)


def build_user_prompt(
    objects: list[str],
    scene: list[str],
    child_name: str,
    child_age: int,
    transcript: str | None,
    story_history: list[dict],
    is_final_beat: bool = False,
) -> str:
    objects_str = ", ".join(objects) if objects else "some interesting things"
    scene_str   = ", ".join(scene)   if scene   else "a cosy room"

    history_lines = "\n".join(
        f"{'Story' if t['role'] == 'model' else child_name}: {t['text']}"
        for t in story_history[-6:]   # rolling 6-turn window
    )

    prompt = f"Child's name: {child_name}, age: {child_age}\n"
    prompt += f"Objects visible: {objects_str}\n"
    prompt += f"Scene: {scene_str}\n"
    if transcript:
        prompt += f"Child just said: \"{transcript}\"\n"
    if history_lines:
        prompt += f"\nRecent story:\n{history_lines}\n"
    if is_final_beat:
        prompt += "\nThis is the final beat — bring the story to a warm, satisfying conclusion.\n"
    prompt += "\nContinue the story. Respond with JSON only."

    return prompt


async def generate_story_beat(
    objects: list[str],
    scene: list[str],
    child_name: str,
    child_age: int,
    transcript: str | None,
    story_history: list[dict],
    is_final_beat: bool = False,
) -> dict:
    """
    Calls the ADK story_agent and parses the JSON response into a dict
    with keys: story_text, question, is_ending.

    Raises ValueError if the response cannot be parsed as valid JSON.
    """
    user_prompt = build_user_prompt(
        objects=objects,
        scene=scene,
        child_name=child_name,
        child_age=child_age,
        transcript=transcript,
        story_history=story_history,
        is_final_beat=is_final_beat,
    )

    logger.info(
        "generate_story_beat: objects=%d, scene=%d, history_turns=%d",
        len(objects), len(scene), len(story_history)
    )

    # ADK agent call
    response = await story_agent.run_async(user_message=user_prompt)
    raw = response.text.strip()

    # Strip accidental markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
        return {
            "story_text": str(parsed.get("story_text", "")),
            "question":   str(parsed.get("question", "What do you think happens next?")),
            "is_ending":  bool(parsed.get("is_ending", False)) or is_final_beat,
        }
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("generate_story_beat: JSON parse failed: %s | raw=%s", exc, raw[:200])
        raise ValueError(f"Story agent returned invalid JSON: {raw[:200]}") from exc
