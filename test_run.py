import traceback
try:
    from aletheia.pipeline import AletheiaPipeline
    p = AletheiaPipeline()
    print("Pipeline OK")

    print("Testing transform...")
    r = p.process_text("새 차를 사고 싶어.")
    print(f"Original: {r.original_text}")
    print(f"Transformed: {r.transformed_text}")
    print("Transform OK")

    print("Testing TTS...")
    audio = p.tts.synthesize(r.transformed_text)
    print(f"Audio bytes: {len(audio)}")
    print("TTS OK")

    print("\nAll tests passed!")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()

input("Press Enter to exit...")
