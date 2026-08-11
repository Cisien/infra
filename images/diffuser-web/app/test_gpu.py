#!/usr/bin/env python3
"""
GPU Performance Validation Script
Tests that the GPU optimizations work correctly
"""

import sys
import os

# Add current directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_gpu_availability():
    """Test that CUDA is available before anything else"""
    print("=== GPU Availability Check ===")

    try:
        import torch
        print(f"PyTorch version: {torch.__version__}")
        print(f"CUDA available: {torch.cuda.is_available()}")

        if not torch.cuda.is_available():
            print("ERROR: CUDA not available!")
            return False, None

        print(f"CUDA device count: {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            print(f"GPU {i}: {torch.cuda.get_device_name(i)} ({props.total_memory / 1024**3:.1f}GB)")

        # Get baseline memory BEFORE loading anything
        torch.cuda.synchronize()
        baseline_memory = torch.cuda.memory_allocated()
        print(f"\nBaseline GPU memory (before loading): {baseline_memory / 1024**3:.2f}GB")

        return True, baseline_memory

    except ImportError as e:
        print(f"ERROR: Could not import torch: {e}")
        return False, None

def test_model_loading(baseline_memory):
    """Test that model loads on GPU without fallbacks"""
    print("\n=== Model Loading Test ===")

    try:
        import torch

        # CRITICAL: Measure memory BEFORE importing app (which loads the model)
        torch.cuda.synchronize()
        memory_before_import = torch.cuda.memory_allocated()
        print(f"GPU memory before import: {memory_before_import / 1024**3:.2f}GB")

        # Now import and load
        from app import load_model, verify_unet_on_gpu, pipe

        print("Loading model...")
        success = load_model()

        if not success:
            print("FAILURE: Model loading failed")
            return False

        # Measure memory AFTER loading
        torch.cuda.synchronize()
        memory_after_load = torch.cuda.memory_allocated()
        memory_used = memory_after_load - memory_before_import

        print(f"\nGPU memory after loading: {memory_after_load / 1024**3:.2f}GB")
        print(f"GPU memory used by model: {memory_used / 1024**3:.2f}GB")

        if memory_used < 1.0:  # Less than 1GB suggests CPU loading
            print("WARNING: Very little GPU memory used - model may be on CPU!")
            return False

        print("SUCCESS: Model loaded to GPU")

        # Verify UNet is on GPU
        print("\n=== UNet GPU Verification ===")
        if not verify_unet_on_gpu():
            print("FAILURE: UNet is not executing on GPU!")
            return False

        # Check component devices
        print("\n=== Component Device Check ===")
        # SDXL components: unet, vae, text_encoder, text_encoder_2
        components = ['unet', 'vae', 'text_encoder', 'text_encoder_2']
        all_on_cuda = True
        for comp_name in components:
            if hasattr(pipe, comp_name):
                comp = getattr(pipe, comp_name)
                if comp is None:
                    continue
                if hasattr(comp, 'device'):
                    print(f"{comp_name}: {comp.device}")
                    if comp.device.type != 'cuda':
                        print(f"ERROR: {comp_name} is not on CUDA!")
                        all_on_cuda = False

        if not all_on_cuda:
            print("FAILURE: Some components are not on CUDA")
            return False

        print("SUCCESS: All components on GPU")
        return True

    except Exception as e:
        print(f"ERROR: Exception during model loading: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_inference_performance():
    """Test that inference actually runs on GPU"""
    print("\n=== GPU Inference Test ===")

    try:
        import torch
        from app import pipe, generate_image_stream
        import time

        if pipe is None:
            print("ERROR: Pipeline not loaded")
            return False

        # Monitor GPU memory before inference
        torch.cuda.synchronize()
        memory_before = torch.cuda.memory_allocated()
        print(f"GPU memory before inference: {memory_before / 1024**3:.2f}GB")

        # Create a simple test generation
        print("Starting test generation...")
        start_time = time.time()

        # This should run on GPU with proper thread context
        success = generate_image_stream(
            prompt="A simple test image",
            width=64,  # Small for quick test
            height=64,
            num_inference_steps=5,  # Minimal steps for speed
            seed=42  # Fixed seed for reproducibility
        )

        # Synchronize to ensure all GPU operations complete
        torch.cuda.synchronize()
        end_time = time.time()

        # Monitor GPU memory after
        memory_after = torch.cuda.memory_allocated()
        memory_delta = memory_after - memory_before

        print(f"GPU memory after inference: {memory_after / 1024**3:.2f}GB")
        print(f"GPU memory delta: {memory_delta:.2f}GB")

        if not success:
            print("FAILURE: Generation failed")
            return False

        elapsed = end_time - start_time
        print(f"SUCCESS: Generation completed in {elapsed:.2f} seconds")

        # Timing check for GPU vs CPU
        if elapsed < 10:
            print("✓ Timing consistent with GPU execution (<10s)")
        elif elapsed < 30:
            print("⚠ Timing slower than expected but may still be GPU")
        else:
            print("✗ WARNING: Timing suggests possible CPU execution (>30s)")

        # Memory check
        if memory_delta > 0.5:  # At least 500MB should be used during inference
            print(f"✓ GPU memory increased by {memory_delta:.2f}GB during inference")
            return True
        else:
            print(f"✗ WARNING: Minimal GPU memory change ({memory_delta:.2f}GB)")
            print("  This may indicate CPU execution!")
            return False

    except Exception as e:
        print(f"ERROR: Exception during inference test: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_multi_gpu_setup():
    """Test multi-GPU distribution if available"""
    print("\n=== Multi-GPU Setup Test ===")

    try:
        import torch
        from app import pipe

        if torch.cuda.device_count() < 2:
            print("Skipping: Only 1 GPU available")
            return True

        print(f"Testing with {torch.cuda.device_count()} GPUs...")

        # Check component distribution (SDXL has text_encoder_2!)
        components = ['unet', 'vae', 'text_encoder', 'text_encoder_2']
        device_counts = {}

        for comp_name in components:
            if hasattr(pipe, comp_name):
                comp = getattr(pipe, comp_name)
                if comp is None:
                    continue
                if hasattr(comp, 'device'):
                    device_id = comp.device.index if comp.device.type == 'cuda' else 'cpu'
                    device_counts[comp_name] = device_id

        print("Component distribution:")
        for comp, device in device_counts.items():
            print(f"  {comp}: GPU {device}")

        # Ideally UNet should be on a different GPU than VAE/text_encoder
        if len(set(device_counts.values())) > 1:
            print("✓ Components distributed across multiple GPUs")
        else:
            print("ℹ All components on same GPU (may not be optimal for multi-GPU)")

        return True

    except Exception as e:
        print(f"ERROR during multi-GPU test: {e}")
        return True  # Don't fail if multi-GPU check fails

def test_threaded_generation():
    """Test that generation works correctly from a background thread.

    This is critical because Flask uses background threads for requests.
    """
    print("\n=== Threaded Generation Test ===")
    print("This test simulates Flask's threaded request handling")

    try:
        import torch
        from app import pipe, ensure_components_on_gpu
        import threading
        import queue
        import time

        if pipe is None:
            print("ERROR: Pipeline not loaded")
            return False

        # Result queue for thread communication
        result_queue = queue.Queue()

        def generate_in_thread():
            """Simulate what Flask does - run generation in background thread"""
            try:
                # Initialize CUDA in this thread (critical!)
                if not torch.cuda.is_initialized():
                    torch.cuda.init()
                torch.cuda.set_device(0)
                torch.cuda.synchronize()

                print(f"  Thread CUDA device: {torch.cuda.current_device()}")

                # Ensure components on GPU (this is the fix!)
                if not ensure_components_on_gpu():
                    result_queue.put(("error", "Failed to ensure components on GPU"))
                    return

                # Check UNet device
                unet_device = next(pipe.unet.parameters()).device
                print(f"  Thread UNet device: {unet_device}")

                if unet_device.type != 'cuda':
                    result_queue.put(("error", f"UNet not on CUDA: {unet_device}"))
                    return

                # Run generation
                generator = torch.Generator(device="cuda:0")
                start = time.time()

                with torch.cuda.device(0):
                    result = pipe(
                        prompt="thread test",
                        width=64,
                        height=64,
                        num_inference_steps=3,
                        generator=generator
                    )

                torch.cuda.synchronize()
                elapsed = time.time() - start

                result_queue.put(("success", elapsed))

            except Exception as e:
                result_queue.put(("error", str(e)))

        # Run generation in background thread
        print("Starting generation in background thread...")
        thread = threading.Thread(target=generate_in_thread)
        thread.start()
        thread.join(timeout=60)  # Wait up to 60 seconds

        if thread.is_alive():
            print("✗ FAILED: Thread timed out (possible CPU hang)")
            return False

        # Get result
        status, data = result_queue.get()

        if status == "error":
            print(f"✗ FAILED: {data}")
            return False

        elapsed = data
        print(f"SUCCESS: Generation completed in {elapsed:.2f}s")

        if elapsed < 10:
            print("✓ Timing consistent with GPU execution")
            return True
        else:
            print("✗ Timing suggests CPU execution")
            return False

    except Exception as e:
        print(f"ERROR in threaded test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("GPU Performance Validation Script")
    print("=" * 60)

    # Step 1: Check GPU availability and get baseline
    gpu_available, baseline_memory = test_gpu_availability()

    if not gpu_available:
        print("\n❌ FATAL: GPU not available!")
        sys.exit(1)

    # Step 2: Test model loading
    loading_success = test_model_loading(baseline_memory)

    if not loading_success:
        print("\n❌ FATAL: Model loading test failed!")
        sys.exit(1)

    # Step 3: Test multi-GPU if available
    test_multi_gpu_setup()

    # Step 4: CRITICAL - Test threaded generation (this is where the bug manifests)
    threaded_success = test_threaded_generation()
    if not threaded_success:
        print("\n❌ CRITICAL: Threaded generation test failed!")
        print("This indicates the CPU fallback bug is present.")
        sys.exit(1)

    # Step 5: Test inference
    inference_success = test_inference_performance()

    if not inference_success:
        print("\n❌ INFERENCE TEST FAILED!")
        print("GPU inference is not working properly.")
        sys.exit(1)

    print("\n🎉 ALL TESTS PASSED!")
    print("Your GPU configuration is working correctly!")
    sys.exit(0)
