# Core types and constants for the Experion chess engine.
#
# Square mapping is little-endian rank-file: a1 = 0, b1 = 1, ..., h8 = 63.
# Piece codes are 0..11 (white pawn = 0 .. black king = 11), so that
# `piece_code = piece_type + 6 * color`.

module Experion
  VERSION = "0.1.0"

  # Colors -------------------------------------------------------------------

  WHITE = 0
  BLACK = 1

  # Piece types --------------------------------------------------------------

  PAWN   = 0
  KNIGHT = 1
  BISHOP = 2
  ROOK   = 3
  QUEEN  = 4
  KING   = 5

  # Piece codes (type + 6*color) ---------------------------------------------

  WP = 0; WN = 1; WB = 2; WR = 3; WQ = 4; WK = 5
  BP = 6; BN = 7; BB = 8; BR = 9; BQ = 10; BK = 11
  NO_PIECE = 12u8

  PIECE_CHAR = "PNBRQKpnbrqk"

  def self.piece_type(pc : Int) : Int32
    pc % 6
  end

  def self.piece_color(pc : Int) : Int32
    pc // 6 == 1 ? BLACK : WHITE
  end

  # Squares ------------------------------------------------------------------

  A1 = 0;  B1 = 1;  C1 = 2;  D1 = 3;  E1 = 4;  F1 = 5;  G1 = 6;  H1 = 7
  A2 = 8;  B2 = 9;  C2 = 10; D2 = 11; E2 = 12; F2 = 13; G2 = 14; H2 = 15
  A3 = 16; B3 = 17; C3 = 18; D3 = 19; E3 = 20; F3 = 21; G3 = 22; H3 = 23
  A4 = 24; B4 = 25; C4 = 26; D4 = 27; E4 = 28; F4 = 29; G4 = 30; H4 = 31
  A5 = 32; B5 = 33; C5 = 34; D5 = 35; E5 = 36; F5 = 37; G5 = 38; H5 = 39
  A6 = 40; B6 = 41; C6 = 42; D6 = 43; E6 = 44; F6 = 45; G6 = 46; H6 = 47
  A7 = 48; B7 = 49; C7 = 50; D7 = 51; E7 = 52; F7 = 53; G7 = 54; H7 = 55
  A8 = 56; B8 = 57; C8 = 58; D8 = 59; E8 = 60; F8 = 61; G8 = 62; H8 = 63

  NO_SQUARE = 255u8

  FILES = "abcdefgh"
  RANKS = "12345678"

  # Castling rights bitmask ----------------------------------------------------
  CASTLE_WK = 1u8
  CASTLE_WQ = 2u8
  CASTLE_BK = 4u8
  CASTLE_BQ = 8u8

  # Move encoding ---------------------------------------------------------------
  #
  # Moves are packed into UInt16:
  #   bits  0..5  from square
  #   bits  6..11 to square
  #   bits 12..14 promotion piece type (0 = none, 1..4 = N,B,R,Q)
  #   bit  15     special flag: en passant if promo==0 else castling
  #
  MOVE_NONE = 0u16

  MAX_PLY     = 128
  MAX_MOVES   = 256

  STARTPOS_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
end
