// AudioWorklet: converts the mic's Float32 samples to Int16LE PCM at 16kHz,
// buffered into 1600-sample (100ms) blocks, and posts each block to the main
// thread as an ArrayBuffer ready to send over the cabin WebSocket.
class PCM16Processor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = [];
    this._blockSize = 1600;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      this._buffer.push(channel[i]);
      if (this._buffer.length >= this._blockSize) {
        this._flush();
      }
    }
    return true;
  }

  _flush() {
    const block = this._buffer.splice(0, this._blockSize);
    const pcm16 = new Int16Array(block.length);
    for (let i = 0; i < block.length; i++) {
      const s = Math.max(-1, Math.min(1, block[i]));
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
  }
}

registerProcessor("pcm16", PCM16Processor);
