// Render performance.json to a WAV with macOS's built-in General MIDI bank.
//
// AVAudioEngine runs in offline manual-rendering mode with an
// AVAudioUnitSampler (program 0, Acoustic Grand Piano, from gs_instruments.dls)
// into a light hall reverb. Note on/off are sent between render calls of 64
// frames, so timing is accurate to about 1.5 ms.
//
// Usage: swift synth.swift performance.json out.wav

import AVFoundation
import AudioToolbox
import Foundation

let args = CommandLine.arguments
guard args.count == 3 else {
    FileHandle.standardError.write("usage: synth performance.json out.wav\n".data(using: .utf8)!)
    exit(2)
}

struct Performance: Decodable {
    let duration: Double
    let events: [[Double]]  // onset s, pitch, velocity, length s
}

let performance = try JSONDecoder().decode(
    Performance.self, from: Data(contentsOf: URL(fileURLWithPath: args[1])))

let bank = URL(fileURLWithPath:
    "/System/Library/Components/CoreAudio.component/Contents/Resources/gs_instruments.dls")

let engine = AVAudioEngine()
let sampler = AVAudioUnitSampler()
let reverb = AVAudioUnitReverb()
reverb.loadFactoryPreset(.mediumHall)
reverb.wetDryMix = 14

engine.attach(sampler)
engine.attach(reverb)
let format = AVAudioFormat(standardFormatWithSampleRate: 44100, channels: 2)!
engine.connect(sampler, to: reverb, format: format)
engine.connect(reverb, to: engine.mainMixerNode, format: format)

let chunk: AVAudioFrameCount = 64
try engine.enableManualRenderingMode(.offline, format: format, maximumFrameCount: chunk)
try engine.start()
try sampler.loadSoundBankInstrument(
    at: bank, program: 0,
    bankMSB: UInt8(kAUSampler_DefaultMelodicBankMSB),
    bankLSB: UInt8(kAUSampler_DefaultBankLSB))

// Flatten to (frame, isOn, pitch, velocity), offs before ons at the same frame.
let rate = format.sampleRate
var changes: [(Int, Bool, UInt8, UInt8)] = []
for e in performance.events {
    let on = Int(e[0] * rate)
    let off = Int((e[0] + e[3]) * rate)
    changes.append((on, true, UInt8(e[1]), UInt8(e[2])))
    changes.append((off, false, UInt8(e[1]), 0))
}
changes.sort { a, b in a.0 != b.0 ? a.0 < b.0 : (!a.1 && b.1) }

let output = try AVAudioFile(
    forWriting: URL(fileURLWithPath: args[2]),
    settings: [
        AVFormatIDKey: kAudioFormatLinearPCM,
        AVSampleRateKey: rate,
        AVNumberOfChannelsKey: 2,
        AVLinearPCMBitDepthKey: 16,
        AVLinearPCMIsFloatKey: false,
    ])
let buffer = AVAudioPCMBuffer(pcmFormat: engine.manualRenderingFormat, frameCapacity: chunk)!

let totalFrames = Int(performance.duration * rate)
var frame = 0
var next = 0
// Sounding notes per pitch, so overlapping repeats of a pitch don't cut each other.
var sounding = [Int](repeating: 0, count: 128)
while frame < totalFrames {
    while next < changes.count && changes[next].0 <= frame {
        let (_, isOn, pitch, velocity) = changes[next]
        if isOn {
            if sounding[Int(pitch)] > 0 { sampler.stopNote(pitch, onChannel: 0) }
            sampler.startNote(pitch, withVelocity: velocity, onChannel: 0)
            sounding[Int(pitch)] += 1
        } else if sounding[Int(pitch)] > 0 {
            sounding[Int(pitch)] -= 1
            if sounding[Int(pitch)] == 0 { sampler.stopNote(pitch, onChannel: 0) }
        }
        next += 1
    }
    let frames = AVAudioFrameCount(min(Int(chunk), totalFrames - frame))
    let status = try engine.renderOffline(frames, to: buffer)
    guard status == .success else {
        FileHandle.standardError.write("render failed: \(status.rawValue)\n".data(using: .utf8)!)
        exit(1)
    }
    try output.write(from: buffer)
    frame += Int(frames)
}
engine.stop()
// Finalise the WAV header (data size); exiting without this leaves it at 0.
if #available(macOS 15.0, *) { output.close() }
print("wrote \(String(format: "%.1f", Double(totalFrames) / rate)) s to \(args[2])")
