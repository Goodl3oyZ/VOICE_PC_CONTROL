interface AudioWaveformProps {
  isRecording: boolean;
  volume: number; // 0 to 1
  isProcessing?: boolean;
}

export function AudioWaveform({ isRecording, volume, isProcessing }: AudioWaveformProps) {
  // 12 waveform bars
  const bars = [0.4, 0.7, 0.5, 0.9, 0.6, 1.0, 0.8, 0.5, 0.9, 0.7, 0.4, 0.6];

  return (
    <div
      className={`waveform-container ${isRecording ? "recording" : ""} ${isProcessing ? "processing" : ""}`}
      aria-hidden="true"
    >
      {bars.map((weight, index) => {
        let heightPercent = 20;
        if (isRecording) {
          // Dynamic height calculated from baseline weight + live volume
          const dynamicBoost = Math.max(0.1, volume * 1.5);
          heightPercent = Math.min(100, Math.max(18, weight * dynamicBoost * 100));
        } else if (isProcessing) {
          heightPercent = 35 + Math.sin((index / bars.length) * Math.PI) * 40;
        }

        return (
          <span
            key={index}
            className="waveform-bar"
            style={{
              height: `${heightPercent}%`,
              animationDelay: `${index * 0.08}s`,
            }}
          />
        );
      })}
    </div>
  );
}
