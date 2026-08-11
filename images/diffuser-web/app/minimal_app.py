#!/usr/bin/env python3
"""
MINIMAL FLUX Web UI - Loads FLUX pipeline with LoRA support
For use with 2x RTX 3090 GPUs
"""

import torch
import sys
import os
from pathlib import Path

# Initialize CUDA immediately
if not torch.cuda.is_available():
    print("FATAL: CUDA not available!")
    sys.exit(1)

torch.cuda.init()
torch.cuda.set_device(0)

print("=" * 60)
print("MINIMAL FLUX WEB UI")
print("=" * 60)
print(f"PyTorch: {torch.__version__}")
print(f"CUDA: {torch.version.cuda}")
print(f"Device: {torch.cuda.get_device_name(0)}")
print(f"Total GPUs: {torch.cuda.device_count()}")
print("=" * 60)

# Global pipeline
pipe = None

def load_pipeline():
    """Load FLUX pipeline with LoRA"""
    global pipe

    print("\nLoading FLUX pipeline...")

    from diffusers import AutoPipelineForText2Image

    # Load base FLUX model
    pipe = AutoPipelineForText2Image.from_pretrained(
        "black-forest-labs/FLUX.1-dev",
        torch_dtype=torch.float16,
        use_safetensors=True,
        safety_checker=None,
    )

    # Move to GPU
    pipe = pipe.to("cuda:0")

    print("✓ Base model loaded on GPU")

    # Load LoRA
    print("\nLoading uncensored LoRA...")
    pipe.load_lora_weights(
        'Heartsync/Flux-NSFW-uncensored',
        weight_name='lora.safetensors',
        adapter_name="uncensored"
    )

    # Set active adapter
    pipe.set_adapters(["uncensored"])

    print("✓ LoRA loaded successfully")

    # Memory info
    torch.cuda.synchronize()
    print(f"\nGPU Memory used: {torch.cuda.memory_allocated() / 1024**3:.2f}GB")

    return True

def generate_image(prompt, negative_prompt="", num_inference_steps=28,
                   guidance_scale=7.0, width=1024, height=1024, seed=None):
    """Generate image using FLUX pipeline"""
    global pipe

    # Ensure CUDA context
    torch.cuda.set_device(0)

    # Set seed
    if seed is not None:
        generator = torch.Generator(device="cuda:0").manual_seed(seed)
    else:
        generator = torch.Generator(device="cuda:0")

    print(f"\nGenerating: {prompt[:50]}...")
    print(f"Steps: {num_inference_steps}, Guidance: {guidance_scale}, Size: {width}x{height}")

    # Generation parameters
    params = {
        "prompt": prompt,
        "num_inference_steps": num_inference_steps,
        "guidance_scale": guidance_scale,
        "width": width,
        "height": height,
        "generator": generator
    }

    if negative_prompt:
        params["negative_prompt"] = negative_prompt

    # Generate
    print("Running FLUX pipeline...")
    with torch.no_grad():
        result = pipe(**params)

    image = result.images[0]

    print("✓ Generation complete")
    return image

if __name__ == "__main__":
    # Load pipeline
    if not load_pipeline():
        print("Failed to load pipeline!")
        sys.exit(1)

    # Test generation
    print("\n" + "=" * 60)
    print("Testing generation...")
    print("=" * 60)

    import time
    start = time.time()

    image = generate_image(
        prompt="A beautiful landscape with mountains and a lake at sunset",
        num_inference_steps=5,  # Quick test with fewer steps
        width=512,
        height=512,
        seed=42
    )

    elapsed = time.time() - start
    print(f"\nGeneration took: {elapsed:.2f}s")

    if elapsed < 60:
        print("✓ Timing suggests GPU execution")
    else:
        print("⚠ Timing suggests slow execution")

    # Save test image
    image.save("test_output_flux.png")
    print("Saved test_output_flux.png")
