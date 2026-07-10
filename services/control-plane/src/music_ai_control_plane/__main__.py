import uvicorn


def main() -> None:
    uvicorn.run(
        "music_ai_control_plane.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()
