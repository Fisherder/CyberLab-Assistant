package sessionwire

import (
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

const (
	FrameStdin  byte = 0x01
	FrameResize byte = 0x02

	MaxPayloadBytes uint32 = 1 << 20
)

var ErrFrameTooLarge = errors.New("sessionwire frame payload too large")

type Resize struct {
	Cols int `json:"cols"`
	Rows int `json:"rows"`
}

func WriteFrame(w io.Writer, frameType byte, payload []byte) error {
	if uint64(len(payload)) > uint64(MaxPayloadBytes) {
		return ErrFrameTooLarge
	}
	header := [5]byte{frameType}
	binary.BigEndian.PutUint32(header[1:], uint32(len(payload)))
	if _, err := w.Write(header[:]); err != nil {
		return err
	}
	if len(payload) == 0 {
		return nil
	}
	_, err := w.Write(payload)
	return err
}

func ReadFrame(r io.Reader) (byte, []byte, error) {
	header := [5]byte{}
	if _, err := io.ReadFull(r, header[:]); err != nil {
		return 0, nil, err
	}
	payloadLen := binary.BigEndian.Uint32(header[1:])
	if payloadLen > MaxPayloadBytes {
		return 0, nil, ErrFrameTooLarge
	}
	payload := make([]byte, payloadLen)
	if payloadLen == 0 {
		return header[0], payload, nil
	}
	if _, err := io.ReadFull(r, payload); err != nil {
		return 0, nil, err
	}
	return header[0], payload, nil
}

func WriteStdin(w io.Writer, payload []byte) error {
	return WriteFrame(w, FrameStdin, payload)
}

func WriteResize(w io.Writer, cols int, rows int) error {
	if cols <= 0 || rows <= 0 {
		return fmt.Errorf("invalid resize dimensions")
	}
	body, err := json.Marshal(Resize{Cols: cols, Rows: rows})
	if err != nil {
		return err
	}
	return WriteFrame(w, FrameResize, body)
}

func DecodeResize(payload []byte) (Resize, error) {
	var resize Resize
	if err := json.Unmarshal(payload, &resize); err != nil {
		return Resize{}, err
	}
	if resize.Cols <= 0 || resize.Rows <= 0 {
		return Resize{}, fmt.Errorf("invalid resize dimensions")
	}
	return resize, nil
}
