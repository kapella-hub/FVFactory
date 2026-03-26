"""
Visual Style Presets - Controls the aesthetic of generated images and script prompts.

Each style defines:
- image_style: Keywords appended to every Flux image prompt
- prompt_rules: Instructions injected into the script generator's system prompt
  (replaces the default photorealistic rules)
- mascot_style: Optional override for mascot prompt styling
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class VisualStyle:
    name: str
    image_style: str
    prompt_rules: str
    mascot_style: Optional[str] = None


VISUAL_STYLES: dict[str, VisualStyle] = {
    "photorealistic": VisualStyle(
        name="Photorealistic",
        image_style="cinematic lighting, photorealistic, natural tones, high detail",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a photorealistic scene. NO cartoons, illustrations, vector art, or anime.
- All prompts must share the SAME visual style: cinematic, realistic, natural lighting, muted tones.
- Describe real-world scenes, objects, and environments. Think National Geographic or documentary footage.
- Include specific details: lighting direction, camera angle, environment, textures.
- NEVER use words like "cartoon", "illustration", "vector", "animated", "cute character", or "art style".
- Think of each image as a frame from a documentary.""",
    ),

    "cartoon": VisualStyle(
        name="Cartoon",
        image_style="2D cartoon style, bold black outlines, flat vibrant colors, exaggerated proportions, clean vector look",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a 2D cartoon scene with bold outlines and flat, vibrant colors.
- Style: modern cartoon like Gravity Falls, Adventure Time, or The Owl House. Exaggerated proportions, expressive characters.
- Use bright saturated colors with clean black outlines. Simple but appealing backgrounds.
- Describe character poses, expressions, and dynamic compositions. Cartoons should feel alive and energetic.
- Include specific details: character expressions, action poses, background elements, color palette.
- Think of each image as a frame from a high-quality animated TV show.""",
        mascot_style="2D cartoon style with bold outlines and vibrant flat colors",
    ),

    "manga": VisualStyle(
        name="Manga",
        image_style="manga art style, black and white ink, dramatic screentones, bold linework, Japanese comic aesthetic",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a Japanese manga scene with bold ink linework and dramatic shading.
- Style: high-contrast black and white manga with screentones, speed lines, and dynamic panel composition.
- Use dramatic angles (low angle, bird's eye, dutch tilt). Manga is ALL about dramatic composition.
- Include action lines, impact effects, dramatic lighting with heavy shadows. Think Berserk, Vagabond, or One Punch Man.
- Characters should have expressive manga eyes, dynamic poses, and exaggerated emotional reactions.
- Describe specific manga techniques: cross-hatching, screentone gradients, speed lines, panel-breaking effects.
- Think of each image as a splash page from a premium manga volume.""",
        mascot_style="manga art style with bold ink lines and screentone shading",
    ),

    "disney": VisualStyle(
        name="Disney/Pixar 3D",
        image_style="Disney Pixar 3D animation style, soft global illumination, subsurface scattering on skin, warm saturated palette, smooth rounded forms",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a scene in Disney/Pixar 3D animation style.
- Style: smooth rounded forms, subsurface scattering on skin, warm color palette, soft global illumination.
- Think Coco, Inside Out, or Encanto. Rich environments, expressive character design, magical lighting.
- Characters should have large expressive eyes, smooth stylized features, and appealing proportions.
- Environments should feel lush and detailed with volumetric lighting and atmospheric depth.
- Include specific details: material textures (fabric folds, hair strands), lighting mood, environmental storytelling.
- Think of each image as a key frame from a Pixar feature film.""",
        mascot_style="Disney Pixar 3D animation style with smooth rounded forms and warm lighting",
    ),

    "stop_motion": VisualStyle(
        name="Stop Motion / Claymation",
        image_style="stop motion claymation style, visible fingerprints on clay, miniature handcrafted set, warm practical lighting, Laika Studios aesthetic",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a stop-motion / claymation scene with handcrafted miniature aesthetics.
- Style: Think Coraline, Kubo, Isle of Dogs, or Wallace & Gromit. Tactile, physical, handmade feel.
- Characters should look sculpted from clay or fabric with visible texture and slight imperfections.
- Environments should feel like intricate miniature sets with practical lighting (real tiny lamps, candles).
- Include details: visible material textures (felt, clay, wood, wire), shallow depth of field, warm tungsten lighting.
- Everything should look like it could physically exist on a tabletop set — tangible and touchable.
- Think of each image as a behind-the-scenes frame from a Laika Studios production.""",
        mascot_style="claymation stop-motion style with visible clay texture and miniature set lighting",
    ),

    "anime": VisualStyle(
        name="Anime",
        image_style="anime cel-shaded style, vivid colors, detailed backgrounds, dramatic lighting, Studio Ghibli meets modern anime aesthetic",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a scene in Japanese anime style with cel-shading and vivid colors.
- Style: blend of Studio Ghibli's detailed backgrounds with modern anime's dynamic character art.
- Use vibrant color palettes with dramatic lighting — golden hour, neon cityscapes, magical glows.
- Characters should have detailed anime features with expressive eyes and dynamic poses.
- Backgrounds should be painterly and atmospheric — think Makoto Shinkai's sky/cloud work or Ghibli's lush landscapes.
- Include specific details: lighting color temperature, atmospheric effects (bokeh, lens flare, particles), composition.
- Think of each image as a key visual from a high-budget anime film.""",
        mascot_style="anime cel-shaded style with vivid colors and detailed features",
    ),

    "watercolor": VisualStyle(
        name="Watercolor",
        image_style="watercolor painting style, soft blended edges, visible paper texture, translucent color washes, dreamy ethereal atmosphere",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a scene rendered in watercolor painting style.
- Style: soft translucent color washes, visible brushstrokes, paper texture bleeding through, wet-on-wet effects.
- Colors should feel luminous and airy — let white space breathe. Think botanical illustration meets fine art.
- Use soft edges that bleed into each other. Hard edges only for key focal points.
- Include details: color wash gradients, splatter effects, dry-brush textures, pencil sketch underdrawing visible beneath paint.
- Compositions should feel artistic and intentional — like pages from a hand-painted picture book.
- Think of each image as a plate from a premium illustrated art book.""",
        mascot_style="watercolor painted style with soft washes and visible brushstrokes",
    ),

    "comic_book": VisualStyle(
        name="Comic Book",
        image_style="American comic book style, bold colors, halftone dot shading, thick ink outlines, dramatic perspective, superhero aesthetic",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a scene in bold American comic book style.
- Style: thick ink outlines, saturated colors, halftone dot shading, dramatic foreshortening. Think Marvel/DC splash pages.
- Use extreme perspective and dynamic compositions — worm's eye, bird's eye, dramatic vanishing points.
- Bold primary colors with cel-shading. Heavy use of black for shadows and dramatic contrast.
- Include action elements: motion blur, impact stars, dramatic lighting with hard shadows.
- Compositions should feel like epic splash pages — bold, dramatic, larger than life.
- Think of each image as a splash page from a premium graphic novel.""",
        mascot_style="comic book style with bold ink outlines and halftone shading",
    ),

    "paper_craft": VisualStyle(
        name="Paper Craft / Collage",
        image_style="paper craft collage style, layered cut paper, visible paper texture and shadows, handmade aesthetic, colorful construction paper",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a scene made from layered cut paper and craft materials.
- Style: paper cutout collage with visible layers, shadows between paper planes, torn edges, textured surfaces.
- Think Eric Carle picture books or Tearaway video game. Handmade, tactile, layered.
- Materials: construction paper, cardboard, tissue paper, fabric scraps, washi tape, yarn.
- Each layer should cast subtle shadows on layers beneath — creating depth from flat materials.
- Include details: paper grain direction, torn vs cut edges, fold creases, tape/glue visible as design elements.
- Think of each image as a page from a handcrafted paper art installation.""",
        mascot_style="paper cutout collage style made from layered colored construction paper",
    ),

    "retro_pixel": VisualStyle(
        name="Retro Pixel Art",
        image_style="pixel art style, 16-bit retro aesthetic, limited color palette, visible pixels, nostalgic video game look",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a scene in 16-bit pixel art style.
- Style: clean pixel art with a limited but carefully chosen color palette (16-32 colors). Think SNES/Genesis era.
- Use dithering for gradients, clear readable silhouettes, and strong color contrast.
- Environments should feel like detailed game backgrounds — layered parallax scrolling aesthetic.
- Characters should be recognizable despite pixel constraints — strong silhouettes and iconic color choices.
- Include details: pixel-level dithering patterns, sub-pixel animation poses, tile-based environment design.
- Think of each image as a key frame from a premium indie pixel art game like Celeste or Hyper Light Drifter.""",
        mascot_style="16-bit pixel art style with clean pixels and limited color palette",
    ),

    "noir": VisualStyle(
        name="Film Noir",
        image_style="film noir style, high contrast black and white, dramatic shadows, venetian blind lighting, 1940s detective aesthetic, grain texture",
        prompt_rules="""CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a scene in classic film noir style.
- Style: high-contrast black and white with dramatic chiaroscuro lighting. Think Double Indemnity, The Third Man.
- Use hard shadows from venetian blinds, street lamps, neon signs. Light cuts through darkness dramatically.
- Environments: rain-slicked streets, smoky rooms, shadowy alleyways, art deco architecture.
- Compositions should use Dutch angles, deep focus, and dramatic silhouettes.
- Include details: film grain texture, light source direction, shadow patterns, fog/smoke atmosphere.
- Think of each image as a frame from a classic 1940s film noir masterpiece.""",
        mascot_style="film noir style in high-contrast black and white with dramatic shadows",
    ),
}


def get_style(name: str) -> VisualStyle:
    """Get a visual style by name. Falls back to 'cartoon' if not found."""
    return VISUAL_STYLES.get(name.lower(), VISUAL_STYLES["cartoon"])


def list_styles() -> list[str]:
    """Return all available style names."""
    return list(VISUAL_STYLES.keys())
