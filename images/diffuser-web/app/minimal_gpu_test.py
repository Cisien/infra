#!/usr/bin/env python3
"""
MINIMAL GPU TEST - Load SDXL components individually
This bypasses all pipeline loading logic and gives us direct control
"""

import torch
import sys

print("=" * 60)
print("MINIMAL SDXL GPU TEST")
print("=" * 60)

# Check CUDA first
print(f"\nPyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")

if not torch.cuda.is_available():
    print("FATAL: CUDA not available!")
    sys.exit(1)

print(f"CUDA device count: {torch.cuda.device_count()}")
for i in range(torch.cuda.device_count()):
    props = torch.cuda.get_device_properties(i)
    print(f"GPU {i}: {torch.cuda.get_device_name(i)} ({props.total_memory / 1024**3:.1f}GB)")

# Initialize CUDA
torch.cuda.init()
torch.cuda.set_device(0)
print(f"\nInitialized CUDA on device 0")

# Get baseline memory
torch.cuda.synchronize()
baseline_memory = torch.cuda.memory_allocated()
print(f"Baseline GPU memory: {baseline_memory / 1024**3:.2f}GB")

print("\n" + "=" * 60)
print("Loading individual components...")
print("=" * 60)

try:
    from diffusers import UNet2DConditionModel, AutoencoderKL
    from transformers import CLIPTextModel, CLIPTextModelWithProjection, CLIPTokenizer
    from diffusers import EulerAncestralDiscreteScheduler

    model_id = "UnfilteredAI/NSFW-gen-v2"

    # Load UNet
    print("\n1. Loading UNet...")
    unet = UNet2DConditionModel.from_pretrained(
        model_id,
        subfolder="unet",
        torch_dtype=torch.float16,
    )
    unet = unet.to("cuda:0")
    unet.eval()
    print(f"   UNet device: {next(unet.parameters()).device}")
    print(f"   UNet dtype: {next(unet.parameters()).dtype}")

    torch.cuda.synchronize()
    mem_after_unet = torch.cuda.memory_allocated()
    print(f"   GPU memory used: {(mem_after_unet - baseline_memory) / 1024**3:.2f}GB")

    # Load VAE
    print("\n2. Loading VAE...")
    vae = AutoencoderKL.from_pretrained(
        model_id,
        subfolder="vae",
        torch_dtype=torch.float16,
    )
    vae = vae.to("cuda:0")
    vae.eval()
    print(f"   VAE device: {next(vae.parameters()).device}")

    # Load text encoder 1
    print("\n3. Loading Text Encoder 1...")
    text_encoder = CLIPTextModel.from_pretrained(
        model_id,
        subfolder="text_encoder",
        torch_dtype=torch.float16,
    )
    text_encoder = text_encoder.to("cuda:0")
    text_encoder.eval()
    print(f"   Text encoder device: {next(text_encoder.parameters()).device}")

    # Load text encoder 2 (SDXL-specific)
    print("\n4. Loading Text Encoder 2...")
    text_encoder_2 = CLIPTextModelWithProjection.from_pretrained(
        model_id,
        subfolder="text_encoder_2",
        torch_dtype=torch.float16,
    )
    text_encoder_2 = text_encoder_2.to("cuda:0")
    text_encoder_2.eval()
    print(f"   Text encoder 2 device: {next(text_encoder_2.parameters()).device}")

    # Load tokenizer
    print("\n5. Loading Tokenizer...")
    tokenizer = CLIPTokenizer.from_pretrained(
        model_id,
        subfolder="tokenizer",
    )
    tokenizer_2 = CLIPTokenizer.from_pretrained(
        model_id,
        subfolder="tokenizer_2",
    )
    print("   Tokenizers loaded (CPU-only)")

    # Load scheduler
    print("\n6. Loading Scheduler...")
    scheduler = EulerAncestralDiscreteScheduler.from_pretrained(
        model_id,
        subfolder="scheduler",
    )
    print("   Scheduler loaded")

    torch.cuda.synchronize()
    total_memory = torch.cuda.memory_allocated()
    print(f"\nTotal GPU memory used: {(total_memory - baseline_memory) / 1024**3:.2f}GB")

except Exception as e:
    print(f"FATAL: Failed to load components: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("Testing UNet forward pass on GPU...")
print("=" * 60)

try:
    # Create test inputs on GPU
    print("\nCreating test tensors on GPU...")
    test_latent = torch.randn(1, 4, 64, 64, device="cuda:0", dtype=torch.float16)
    test_timestep = torch.tensor([999], device="cuda:0")
    # SDXL uses 2048 dim for encoder_hidden_states
    test_encoder_hidden_states = torch.randn(1, 77, 2048, device="cuda:0", dtype=torch.float16)

    # SDXL requires added_cond_kwargs with text_embeds and time_ids
    test_text_embeds = torch.randn(1, 1280, device="cuda:0", dtype=torch.float16)  # Pooled embeddings
    test_time_ids = torch.zeros(1, 6, device="cuda:0", dtype=torch.float16)  # SDXL time ids

    print(f"Test latent device: {test_latent.device}")
    print(f"Test timestep device: {test_timestep.device}")
    print(f"Test encoder states device: {test_encoder_hidden_states.device}")

    # Warm-up with SDXL-specific arguments
    print("\nWarming up UNet...")
    with torch.no_grad():
        _ = unet(
            test_latent,
            test_timestep,
            test_encoder_hidden_states,
            added_cond_kwargs={
                "text_embeds": test_text_embeds,
                "time_ids": test_time_ids
            }
        ).sample
    torch.cuda.synchronize()

    # Timed run
    print("Running timed UNet forward pass...")
    start_event = torch.cuda.Event(enable_timing=True)
    end_event = torch.cuda.Event(enable_timing=True)

    start_event.record()
    with torch.no_grad():
        output = unet(
            test_latent,
            test_timestep,
            test_encoder_hidden_states,
            added_cond_kwargs={
                "text_embeds": test_text_embeds,
                "time_ids": test_time_ids
            }
        ).sample
    end_event.record()

    torch.cuda.synchronize()
    elapsed_ms = start_event.elapsed_time(end_event)

    print(f"\nUNet forward pass time: {elapsed_ms:.2f}ms")
    print(f"Output device: {output.device}")

    if elapsed_ms < 100:
        print("✓ PASS: Timing consistent with GPU execution (<100ms)")
        gpu_working = True
    elif elapsed_ms < 500:
        print("⚠ WARNING: Slower than expected but likely GPU")
        gpu_working = True
    else:
        print("✗ FAIL: Timing suggests CPU execution (>500ms)")
        gpu_working = False

except Exception as e:
    print(f"FATAL: UNet test failed: {e}")
    import traceback
    traceback.print_exc()
    gpu_working = False

print("\n" + "=" * 60)
if gpu_working:
    print("✓ GPU TEST PASSED")
    print("Individual components work correctly on GPU!")
else:
    print("✗ GPU TEST FAILED")
    print("Components are not executing on GPU")
print("=" * 60)

sys.exit(0 if gpu_working else 1)
